from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.api.serializers import ClientType, UserSerializer
from apps.accounts.models import User, normalize_email_address
from apps.common.fields import currency_code_validator

from ..catalog import ALL_CODES
from ..context import RequestContext
from ..models import (
    Invitation,
    Membership,
    Organization,
    Permission,
    Role,
    Store,
    TenantModel,
    store_code_validator,
    validate_timezone,
)

# --- Helpers ----------------------------------------------------------------------


def _ctx(serializer: serializers.Field[Any, Any, Any, Any]) -> RequestContext:
    ctx = serializer.context.get("ctx")
    if not isinstance(ctx, RequestContext):  # pragma: no cover - programming error
        raise RuntimeError("Serializer needs the request context")
    return ctx


@extend_schema_field(OpenApiTypes.UUID)
class ScopedPrimaryKeyField(serializers.PrimaryKeyRelatedField):  # type: ignore[type-arg]
    """Resolves IDs only within the caller's organization.

    An ID from another business fails exactly like an ID that does not exist
    ("does_not_exist"), so responses reveal nothing about other tenants.
    """

    def __init__(self, model: type[TenantModel], **kwargs: Any) -> None:
        self.model = model
        super().__init__(**kwargs)

    def get_queryset(self) -> Any:
        return self.model.objects.for_org(_ctx(self).organization)


def _check_password(password: str, *, email: str, full_name: str) -> None:
    try:
        validate_password(password, user=User(email=email, full_name=full_name))
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"password": list(exc.messages)}) from exc


# --- Sign-up and session ------------------------------------------------------------------


class SignupSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    full_name = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    organization_name = serializers.CharField(max_length=150)
    store_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    currency = serializers.CharField(default="KES", validators=[currency_code_validator])
    timezone = serializers.CharField(default="Africa/Nairobi", validators=[validate_timezone])
    client = serializers.ChoiceField(choices=ClientType.CHOICES, default=ClientType.WEB)
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_email(self, value: str) -> str:
        email = normalize_email_address(value)
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists. Sign in instead.", code="taken"
            )
        return email

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _check_password(attrs["password"], email=attrs["email"], full_name=attrs["full_name"])
        return attrs


class SwitchOrganizationSerializer(serializers.Serializer[dict[str, Any]]):
    organization_id = serializers.UUIDField()


# --- Organization and stores ------------------------------------------------------------


class OrganizationSerializer(serializers.ModelSerializer[Organization]):
    class Meta:
        model = Organization
        fields = (
            "id", "name", "base_currency", "timezone", "locale", "tax_mode", "status",
            "created_at",
        )  # fmt: skip
        read_only_fields = ("id", "base_currency", "status", "created_at")


class StoreSerializer(serializers.ModelSerializer[Store]):
    # Declared explicitly so input is upper-cased before the format check runs.
    code = serializers.CharField(max_length=20)
    currency = serializers.CharField(required=False, validators=[currency_code_validator])
    timezone = serializers.CharField(required=False, validators=[validate_timezone])

    class Meta:
        model = Store
        fields = (
            "id", "code", "name", "address", "phone", "currency", "timezone", "is_active",
            "created_at",
        )  # fmt: skip
        read_only_fields: tuple[str, ...] = ("id", "created_at")

    def validate_code(self, value: str) -> str:
        code = value.strip().upper()
        try:
            store_code_validator(code)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages), code="invalid") from exc
        if Store.objects.for_org(_ctx(self).organization).filter(code=code).exists():
            raise serializers.ValidationError("Another store already uses this code.", code="taken")
        return code


class StoreUpdateSerializer(StoreSerializer):
    # Explicitly declared fields ignore Meta.read_only_fields, so redeclare.
    code = serializers.CharField(read_only=True)
    currency = serializers.CharField(read_only=True)

    class Meta(StoreSerializer.Meta):
        # Code and currency appear on receipt numbers and money records.
        read_only_fields = ("id", "code", "currency", "created_at")


class StoreSummarySerializer(serializers.ModelSerializer[Store]):
    class Meta:
        model = Store
        fields = ("id", "code", "name")
        read_only_fields = fields


# --- Roles ---------------------------------------------------------------------------------


class PermissionSerializer(serializers.ModelSerializer[Permission]):
    class Meta:
        model = Permission
        fields = ("code", "description", "category", "is_sensitive")
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer[Role]):
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(ALL_CODES)),
        allow_empty=True,
        source="permission_codes",
    )
    description = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )

    class Meta:
        model = Role
        fields = ("id", "name", "description", "template", "is_system", "permissions", "created_at")
        read_only_fields = ("id", "template", "is_system", "created_at")

    def validate_name(self, value: str) -> str:
        roles = Role.objects.for_org(_ctx(self).organization).filter(name__iexact=value.strip())
        if self.instance is not None:
            roles = roles.exclude(pk=self.instance.pk)
        if roles.exists():
            raise serializers.ValidationError("Another role already has this name.", code="taken")
        return value.strip()


class RoleSummarySerializer(serializers.ModelSerializer[Role]):
    class Meta:
        model = Role
        fields = ("id", "name", "template")
        read_only_fields = fields


# --- Members --------------------------------------------------------------------------------


class MemberUserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ("id", "email", "full_name")
        read_only_fields = fields


class MemberSerializer(serializers.ModelSerializer[Membership]):
    user = MemberUserSerializer(read_only=True)
    role = RoleSummarySerializer(read_only=True)
    stores = StoreSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Membership
        fields = ("id", "user", "role", "all_stores", "stores", "status", "version", "created_at")
        read_only_fields = fields


class MemberCreateSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    full_name = serializers.CharField(max_length=150)
    password = serializers.CharField(
        max_length=128,
        write_only=True,
        trim_whitespace=False,
        help_text="Initial password for the new account. Share it with the person privately.",
    )
    role_id = ScopedPrimaryKeyField(Role)
    all_stores = serializers.BooleanField(default=False)
    store_ids = ScopedPrimaryKeyField(Store, many=True, required=False, default=list)

    def validate_email(self, value: str) -> str:
        email = normalize_email_address(value)
        if User.objects.filter(email=email).exists():
            # Adding existing accounts needs their consent: invitations (Phase 1.9).
            raise serializers.ValidationError(
                "This email already has a ShopFlow account. Invite them instead, so they "
                "can accept with their own sign-in.",
                code="account_exists",
            )
        return email

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs["all_stores"] and not attrs["store_ids"]:
            raise serializers.ValidationError(
                {"store_ids": ["Choose at least one store, or give access to all stores."]}
            )
        _check_password(attrs["password"], email=attrs["email"], full_name=attrs["full_name"])
        return attrs


class MemberUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    version = serializers.IntegerField(
        help_text="The version you last read; the update is refused if someone changed it since."
    )
    role_id = ScopedPrimaryKeyField(Role, required=False)
    all_stores = serializers.BooleanField(required=False)
    store_ids = ScopedPrimaryKeyField(Store, many=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("all_stores") is False and not attrs.get("store_ids"):
            raise serializers.ValidationError(
                {"store_ids": ["Choose at least one store, or give access to all stores."]}
            )
        return attrs


class SuspendSerializer(serializers.Serializer[dict[str, Any]]):
    reason = serializers.CharField(max_length=500)


# --- Who am I ---------------------------------------------------------------------------------


class MembershipSummarySerializer(serializers.Serializer[dict[str, Any]]):
    organization_id = serializers.UUIDField()
    organization_name = serializers.CharField()
    role = serializers.CharField()


class CurrentAccessSerializer(serializers.Serializer[dict[str, Any]]):
    role = RoleSummarySerializer()
    permissions = serializers.ListField(child=serializers.CharField())
    all_stores = serializers.BooleanField()
    stores = StoreSummarySerializer(many=True)


class InvitationSerializer(serializers.ModelSerializer[Invitation]):
    role = RoleSummarySerializer(read_only=True)
    invited_by = serializers.CharField(source="invited_by.full_name", read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Invitation
        fields = (
            "id", "email", "role", "all_stores", "store_ids", "status", "invited_by",
            "expires_at", "created_at",
        )  # fmt: skip
        read_only_fields = fields


class InvitationCreateSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    role_id = ScopedPrimaryKeyField(Role)
    all_stores = serializers.BooleanField(default=False)
    store_ids = ScopedPrimaryKeyField(Store, many=True, required=False, default=list)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs["all_stores"] and not attrs["store_ids"]:
            raise serializers.ValidationError(
                {"store_ids": ["Choose at least one store, or give access to all stores."]}
            )
        return attrs


class InvitationTokenSerializer(serializers.Serializer[dict[str, Any]]):
    token = serializers.CharField(max_length=128)


class InvitationPreviewSerializer(serializers.Serializer[dict[str, Any]]):
    organization_name = serializers.CharField()
    email = serializers.EmailField()
    role_name = serializers.CharField()
    account_exists = serializers.BooleanField(
        help_text="If true, sign in as this email before accepting."
    )
    expires_at = serializers.DateTimeField()


class InvitationAcceptSerializer(serializers.Serializer[dict[str, Any]]):
    token = serializers.CharField(max_length=128)
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(
        max_length=128, required=False, write_only=True, trim_whitespace=False
    )
    client = serializers.ChoiceField(choices=ClientType.CHOICES, default=ClientType.WEB)


class InvitationAcceptedSerializer(serializers.Serializer[dict[str, Any]]):
    organization_id = serializers.UUIDField()


class MeSerializer(serializers.Serializer[dict[str, Any]]):
    mfa_verified = serializers.BooleanField(
        help_text="This session passed two-step verification (needed for sensitive actions)."
    )
    user = UserSerializer()
    organization = OrganizationSerializer(allow_null=True)
    access = CurrentAccessSerializer(allow_null=True)
    organizations = MembershipSummarySerializer(
        many=True, help_text="Businesses this user can switch to."
    )
