"""Tenancy use cases: sign-up, organization and store settings, staff and roles.

Every change is audited in the same transaction. The privilege rules
(docs/SECURITY.md §3.5) are enforced here, not in views:

* you can only grant permissions you hold yourself (roles and role assignment);
* you can only manage staff whose role you could have assigned;
* you cannot change your own role, stores or status;
* store access you grant must be within your own store access;
* a business always keeps at least one active Owner.
"""

import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User, normalize_email_address
from apps.accounts.services import revoke_organization_sessions
from apps.audit.services import AuditActor, diff, record_audit
from apps.catalog.services import create_default_catalog
from apps.payments.services import create_default_payment_methods

from .catalog import OWNER_ROLE_DESCRIPTION, OWNER_ROLE_NAME, ROLE_TEMPLATES
from .context import RequestContext, invalidate_membership, invalidate_role, role_permissions
from .errors import (
    AlreadyAMember,
    CannotModifySelf,
    LastOwner,
    PrivilegeEscalation,
    SystemRoleImmutable,
)
from .models import Membership, MembershipStore, Organization, Role, RolePermission, Store

DEFAULT_STORE_CODE = "MAIN"


# --- Sign-up ------------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredBusiness:
    user: User
    organization: Organization
    store: Store
    membership: Membership


def register_business(
    *,
    email: str,
    full_name: str,
    password: str,
    organization_name: str,
    currency: str,
    timezone: str,
    store_name: str = "",
    ip_address: str | None = None,
    user_agent: str = "",
) -> RegisteredBusiness:
    """Create an owner account, their business, default roles and a first store."""
    with transaction.atomic():
        user = User.objects.create_user(
            normalize_email_address(email), password, full_name=full_name
        )
        organization = Organization.objects.create(
            name=organization_name,
            slug=_unique_slug(organization_name),
            base_currency=currency,
            timezone=timezone,
        )
        owner_role = _create_default_roles(organization)
        store = Store.objects.create(
            organization=organization,
            code=DEFAULT_STORE_CODE,
            name=store_name or "Main store",
            currency=currency,
            timezone=timezone,
        )
        _add_default_till(store)
        membership = Membership.objects.create(
            organization=organization, user=user, role=owner_role, all_stores=True
        )
        actor = AuditActor(
            organization_id=organization.pk,
            user_id=user.pk,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        record_audit(
            actor,
            action="organization.created",
            entity_type="organization",
            entity_id=organization.pk,
            changes={"name": [None, organization.name], "base_currency": [None, currency]},
        )
        record_audit(
            actor,
            action="store.created",
            entity_type="store",
            entity_id=store.pk,
            store_id=store.pk,
            changes={"code": [None, store.code], "name": [None, store.name]},
        )
        create_default_catalog(organization, actor)
        create_default_payment_methods(organization, actor)
    return RegisteredBusiness(
        user=user, organization=organization, store=store, membership=membership
    )


def _add_default_till(store: Store) -> None:
    """Every store starts with one cash drawer, so the till can be opened straight away."""
    from apps.cash.models import Till  # the cash app builds on this one

    Till.objects.create(organization_id=store.organization_id, store=store, name="Till 1")


def _unique_slug(name: str) -> str:
    base = slugify(name)[:48] or "business"
    return f"{base}-{secrets.token_hex(3)}"


def _create_default_roles(organization: Organization) -> Role:
    owner = Role.objects.create(
        organization=organization,
        name=OWNER_ROLE_NAME,
        description=OWNER_ROLE_DESCRIPTION,
        template=Role.Template.OWNER,
        is_system=True,
    )
    for template, (name, description, codes) in ROLE_TEMPLATES.items():
        role = Role.objects.create(
            organization=organization, name=name, description=description, template=template
        )
        RolePermission.objects.bulk_create(
            RolePermission(role=role, permission_id=code) for code in sorted(codes)
        )
    return owner


# --- Organization and stores ------------------------------------------------------


def update_organization(ctx: RequestContext, **changes: Any) -> Organization:
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=ctx.organization.pk)
        before = {field: getattr(organization, field) for field in changes}
        for field, value in changes.items():
            setattr(organization, field, value)
        organization.save()
        _audit(ctx, "organization.updated", "organization", organization.pk, before, changes)
    return organization


def create_store(ctx: RequestContext, **fields: Any) -> Store:
    fields.setdefault("currency", ctx.organization.base_currency)
    fields.setdefault("timezone", ctx.organization.timezone)
    with transaction.atomic():
        store = Store.objects.create(organization=ctx.organization, **fields)
        _add_default_till(store)
        record_audit(
            ctx.audit_actor,
            action="store.created",
            entity_type="store",
            entity_id=store.pk,
            store_id=store.pk,
            changes={field: [None, value] for field, value in fields.items()},
        )
    return store


def update_store(ctx: RequestContext, store: Store, **changes: Any) -> Store:
    with transaction.atomic():
        store = Store.objects.for_org(ctx.organization).select_for_update().get(pk=store.pk)
        before = {field: getattr(store, field) for field in changes}
        for field, value in changes.items():
            setattr(store, field, value)
        store.save()
        _audit(ctx, "store.updated", "store", store.pk, before, changes, store_id=store.pk)
    return store


# --- Roles ----------------------------------------------------------------------------


def create_role(
    ctx: RequestContext, *, name: str, description: str, permissions: Iterable[str]
) -> Role:
    codes = frozenset(permissions)
    _require_grantable(ctx, codes)
    with transaction.atomic():
        role = Role.objects.create(
            organization=ctx.organization, name=name, description=description
        )
        RolePermission.objects.bulk_create(
            RolePermission(role=role, permission_id=code) for code in sorted(codes)
        )
        record_audit(
            ctx.audit_actor,
            action="role.created",
            entity_type="role",
            entity_id=role.pk,
            changes={"name": [None, name], "permissions": [[], sorted(codes)]},
        )
    return role


def update_role(
    ctx: RequestContext,
    role: Role,
    *,
    name: str | None = None,
    description: str | None = None,
    permissions: Iterable[str] | None = None,
) -> Role:
    if role.is_system:
        raise SystemRoleImmutable("The Owner role always has full access and cannot be edited.")
    with transaction.atomic():
        role = Role.objects.for_org(ctx.organization).select_for_update().get(pk=role.pk)
        current = frozenset(
            RolePermission.objects.filter(role=role).values_list("permission_id", flat=True)
        )
        _require_grantable(ctx, current)  # cannot edit roles more powerful than your own
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        if name is not None and name != role.name:
            before["name"], after["name"] = role.name, name
            role.name = name
        if description is not None and description != role.description:
            before["description"], after["description"] = role.description, description
            role.description = description
        if permissions is not None:
            requested = frozenset(permissions)
            _require_grantable(ctx, requested)
            if requested != current:
                RolePermission.objects.filter(role=role).exclude(
                    permission_id__in=requested
                ).delete()
                RolePermission.objects.bulk_create(
                    [
                        RolePermission(role=role, permission_id=code)
                        for code in sorted(requested - current)
                    ]
                )
                before["permissions"], after["permissions"] = current, requested
        role.save()
        _audit(ctx, "role.updated", "role", role.pk, before, after)
        transaction.on_commit(lambda: invalidate_role(role.pk))
    invalidate_role(role.pk)
    return role


# --- Members ----------------------------------------------------------------------------


def add_member(
    ctx: RequestContext,
    *,
    email: str,
    full_name: str,
    password: str | None,
    role: Role,
    all_stores: bool,
    stores: Iterable[Store],
) -> Membership:
    """Give a person access to this business, creating their account if needed.

    An existing account keeps its own name and password: one business can
    never change another account's credentials.
    """
    store_list = list(stores)
    _require_assignable(ctx, role)
    _require_store_scope(ctx, all_stores, store_list)
    normalized = normalize_email_address(email)
    with transaction.atomic():
        user = User.objects.filter(email=normalized).first()
        created_account = user is None
        if user is None:
            user = User.objects.create_user(normalized, password, full_name=full_name)
        elif Membership.objects.for_org(ctx.organization).filter(user=user).exists():
            raise AlreadyAMember("This person is already a member of your business.")

        membership = Membership.objects.create(
            organization=ctx.organization, user=user, role=role, all_stores=all_stores
        )
        _set_stores(membership, [] if all_stores else store_list)
        record_audit(
            ctx.audit_actor,
            action="membership.added",
            entity_type="membership",
            entity_id=membership.pk,
            changes={
                "user": [None, str(user.pk)],
                "role": [None, role.name],
                "all_stores": [None, all_stores],
                "stores": [[], sorted(s.code for s in store_list)],
                "account_created": [None, created_account],
            },
        )
    return membership


def update_member(
    ctx: RequestContext,
    membership: Membership,
    *,
    role: Role | None = None,
    all_stores: bool | None = None,
    stores: Iterable[Store] | None = None,
) -> Membership:
    with transaction.atomic():
        membership = _lock_member(ctx, membership)
        _require_manageable(ctx, membership)
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}

        if role is not None and role.pk != membership.role_id:
            _require_assignable(ctx, role)
            if membership.role.is_owner and not role.is_owner:
                _require_another_owner(ctx, membership)
            before["role"], after["role"] = membership.role.name, role.name
            membership.role = role

        if all_stores is not None or stores is not None:
            new_all = membership.all_stores if all_stores is None else all_stores
            new_stores = list(stores) if stores is not None else list(membership.stores.all())
            _require_store_scope(ctx, new_all, new_stores)
            old_codes = sorted(s.code for s in membership.stores.all())
            new_codes = [] if new_all else sorted(s.code for s in new_stores)
            if new_all != membership.all_stores or old_codes != new_codes:
                before.update(all_stores=membership.all_stores, stores=old_codes)
                after.update(all_stores=new_all, stores=new_codes)
                membership.all_stores = new_all
                _set_stores(membership, [] if new_all else new_stores)

        if after:
            membership.version += 1
            membership.save()
            _audit(ctx, "membership.updated", "membership", membership.pk, before, after)
            transaction.on_commit(lambda: invalidate_membership(membership.pk))
    invalidate_membership(membership.pk)
    return membership


def suspend_member(ctx: RequestContext, membership: Membership, *, reason: str) -> Membership:
    """Suspend access immediately: the person's sessions for this business end now."""
    with transaction.atomic():
        membership = _lock_member(ctx, membership)
        _require_manageable(ctx, membership)
        if membership.status == Membership.Status.SUSPENDED:
            return membership
        if membership.role.is_owner:
            _require_another_owner(ctx, membership)
        membership.status = Membership.Status.SUSPENDED
        membership.version += 1
        membership.save()
        revoke_organization_sessions(
            user_id=membership.user_id, organization_id=ctx.organization.pk
        )
        record_audit(
            ctx.audit_actor,
            action="membership.suspended",
            entity_type="membership",
            entity_id=membership.pk,
            changes={"status": ["ACTIVE", "SUSPENDED"]},
            reason=reason,
        )
    return membership


def reactivate_member(ctx: RequestContext, membership: Membership) -> Membership:
    with transaction.atomic():
        membership = _lock_member(ctx, membership)
        _require_manageable(ctx, membership)
        if membership.status == Membership.Status.ACTIVE:
            return membership
        membership.status = Membership.Status.ACTIVE
        membership.version += 1
        membership.save()
        record_audit(
            ctx.audit_actor,
            action="membership.reactivated",
            entity_type="membership",
            entity_id=membership.pk,
            changes={"status": ["SUSPENDED", "ACTIVE"]},
        )
    return membership


# --- Rules --------------------------------------------------------------------------------


def _require_grantable(ctx: RequestContext, codes: frozenset[str]) -> None:
    missing = codes - ctx.permissions
    if missing:
        raise PrivilegeEscalation(
            "You can only grant permissions that you have yourself.",
            errors=[
                {
                    "pointer": "/permissions",
                    "code": "NOT_HELD",
                    "meta": {"permissions": sorted(missing)},
                }
            ],
        )


def _require_assignable(ctx: RequestContext, role: Role) -> None:
    if role.is_owner and not ctx.is_owner:
        raise PrivilegeEscalation("Only an owner can make someone an owner.")
    _require_grantable(ctx, role_permissions(role))


def _require_manageable(ctx: RequestContext, membership: Membership) -> None:
    if membership.user_id == ctx.user.pk:
        raise CannotModifySelf("You can't change your own access. Ask another owner or manager.")
    _require_assignable(ctx, membership.role)


def _require_store_scope(ctx: RequestContext, all_stores: bool, stores: list[Store]) -> None:
    if ctx.all_stores:
        return
    outside = [s.code for s in stores if s.pk not in ctx.store_ids]
    if all_stores or outside:
        raise PrivilegeEscalation(
            "You can only give access to stores you have access to yourself.",
            errors=[{"pointer": "/store_ids", "code": "NOT_HELD", "meta": {"stores": outside}}],
        )


def _require_another_owner(ctx: RequestContext, membership: Membership) -> None:
    # Lock the owners so two owners cannot demote each other at the same time.
    owners = list(
        Membership.objects.for_org(ctx.organization)
        .select_for_update()
        .filter(role__template=Role.Template.OWNER, status=Membership.Status.ACTIVE)
        .exclude(pk=membership.pk)
        .values_list("pk", flat=True)
    )
    if not owners:
        raise LastOwner("A business must keep at least one active owner.")


def _lock_member(ctx: RequestContext, membership: Membership) -> Membership:
    return (
        Membership.objects.for_org(ctx.organization)
        .select_for_update(of=("self",))
        .select_related("role", "user")
        .get(pk=membership.pk)
    )


def _set_stores(membership: Membership, stores: list[Store]) -> None:
    MembershipStore.objects.filter(membership=membership).delete()
    MembershipStore.objects.bulk_create(
        MembershipStore(membership=membership, store=store) for store in stores
    )


def _audit(
    ctx: RequestContext,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    store_id: uuid.UUID | None = None,
) -> None:
    changes = diff(before, after)
    if changes:
        record_audit(
            ctx.audit_actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes,
            store_id=store_id,
        )
