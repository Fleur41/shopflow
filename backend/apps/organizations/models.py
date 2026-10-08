import zoneinfo
from typing import Any, ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from apps.common.fields import CurrencyField
from apps.common.models import BaseModel


def validate_timezone(value: str) -> None:
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f"Unknown time zone: {value}")


class Organization(BaseModel):
    """A business: the tenant boundary. No data is ever shared across organizations."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=60, unique=True)
    base_currency = CurrencyField(help_text="Default currency for new stores. Fixed once set.")
    timezone = models.CharField(max_length=64, validators=[validate_timezone])
    locale = models.CharField(max_length=16, default="en")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(status__in=["ACTIVE", "SUSPENDED"]),
                name="organizations_org_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name


# --- Tenant scoping -----------------------------------------------------------


class UnscopedQueryError(RuntimeError):
    """A tenant-owned model was queried without saying which organization."""


class TenantManager[M: models.Model](models.Manager[M]):
    """``Model.objects`` for tenant-owned models: every query must be scoped.

    ``Store.objects.for_org(org)`` works; ``Store.objects.all()`` raises
    :class:`UnscopedQueryError`, so a forgotten tenant filter fails loudly
    in development and tests instead of leaking data in production
    (docs/ARCHITECTURE.md, ADR-03). Django internals (admin, related
    managers, validators) use the plain ``unscoped`` manager, which is the
    model's default manager.
    """

    def get_queryset(self) -> models.QuerySet[M]:
        raise UnscopedQueryError(
            f"{self.model.__name__}.objects must be scoped: use "
            f".for_org(organization) or, for platform code, .unscoped"
        )

    def for_org(self, organization: "Organization | Any") -> models.QuerySet[M]:
        organization_id = getattr(organization, "pk", organization)
        if organization_id is None:
            raise UnscopedQueryError("for_org() needs an organization")
        return super().get_queryset().filter(organization_id=organization_id)

    def create(self, **kwargs: Any) -> M:
        if kwargs.get("organization") is None and kwargs.get("organization_id") is None:
            raise UnscopedQueryError(f"{self.model.__name__} must be created with an organization")
        return super().get_queryset().create(**kwargs)


class TenantModel(BaseModel):
    """Base for every model owned by an organization.

    ``unscoped`` is declared first so it becomes Django's default manager.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="+", db_index=True
    )

    unscoped: ClassVar[models.Manager[Any]] = models.Manager()
    objects: ClassVar[TenantManager[Any]] = TenantManager()

    class Meta:
        abstract = True


# --- Stores --------------------------------------------------------------------

store_code_validator = RegexValidator(
    regex=r"^[A-Z0-9]{2,10}$",
    message="Use 2-10 capital letters or digits (it appears on receipt numbers).",
)


class Store(TenantModel):
    objects: ClassVar[TenantManager["Store"]]
    """A shop location. Code and currency are fixed after creation because they
    appear on receipt numbers and financial records."""

    code = models.CharField(max_length=10, validators=[store_code_validator])
    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    currency = CurrencyField()
    timezone = models.CharField(max_length=64, validators=[validate_timezone])
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "code"], name="organizations_store_code_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[A-Z0-9]{2,10}$"),
                name="organizations_store_code_format",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"


# --- Roles and permissions ---------------------------------------------------------


class Permission(models.Model):
    """A business permission code. Rows mirror ``catalog.CATALOG`` (synced after migrate)."""

    code = models.CharField(max_length=64, primary_key=True)
    description = models.CharField(max_length=200)
    category = models.CharField(max_length=32)
    is_sensitive = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.code


class Role(TenantModel):
    objects: ClassVar[TenantManager["Role"]]

    class Template(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Manager"
        CASHIER = "CASHIER", "Cashier"
        CUSTOM = "CUSTOM", "Custom"

    name = models.CharField(max_length=60)
    description = models.CharField(max_length=255, blank=True)
    template = models.CharField(max_length=10, choices=Template.choices, default=Template.CUSTOM)
    is_system = models.BooleanField(
        default=False, help_text="System roles (Owner) cannot be edited or deleted."
    )
    permissions: "models.ManyToManyField[Permission, RolePermission]" = models.ManyToManyField(
        Permission, through="RolePermission", related_name="+"
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="organizations_role_name_unique"
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(template="OWNER"),
                name="organizations_one_owner_role",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_owner(self) -> bool:
        return self.template == self.Template.OWNER

    @property
    def permission_codes(self) -> list[str]:
        """Sorted codes this role grants (Owner: every code, including future ones)."""
        from .context import role_permissions

        return sorted(role_permissions(self))


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["role", "permission"], name="organizations_role_permission_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.role_id}:{self.permission_id}"


# --- Memberships -------------------------------------------------------------------


class Membership(TenantModel):
    objects: ClassVar[TenantManager["Membership"]]
    """A user's access to an organization: one role, in all or some stores."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    all_stores = models.BooleanField(default=False)
    stores: "models.ManyToManyField[Store, MembershipStore]" = models.ManyToManyField(
        Store, through="MembershipStore", related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "organization"], name="organizations_membership_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["ACTIVE", "SUSPENDED"]),
                name="organizations_membership_status_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.organization_id}"


class MembershipStore(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    store = models.ForeignKey(Store, on_delete=models.PROTECT)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["membership", "store"], name="organizations_membership_store_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.membership_id}:{self.store_id}"


# --- Invitations ------------------------------------------------------------------


class Invitation(TenantModel):
    """An emailed offer to join the business. Accepting needs the emailed token,
    and for existing accounts, signing in as that account (their consent)."""

    objects: ClassVar[TenantManager["Invitation"]]

    email = models.EmailField(max_length=254)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="+")
    all_stores = models.BooleanField(default=False)
    store_ids = models.JSONField(default=list, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="organizations_one_pending_invitation",
            ),
        ]

    def __str__(self) -> str:
        return f"invitation for {self.email}"

    @property
    def status(self) -> str:
        from django.utils import timezone

        if self.accepted_at:
            return "ACCEPTED"
        if self.revoked_at:
            return "REVOKED"
        if self.expires_at <= timezone.now():
            return "EXPIRED"
        return "PENDING"
