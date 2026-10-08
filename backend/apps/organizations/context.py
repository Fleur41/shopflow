"""Per-request tenant context: who is acting, for which organization, with what rights.

The organization comes only from the authenticated session, never from the
request body or query string (docs/SECURITY.md §4). Membership status, role
and organization status are read fresh on every request; the role's
permission codes and the membership's store list are cached and invalidated
whenever they change.
"""

import uuid
from dataclasses import dataclass

from django.core.cache import cache
from rest_framework.request import Request

from apps.accounts.models import User
from apps.accounts.services import get_session_state
from apps.accounts.tokens import AccessClaims
from apps.audit.services import AuditActor
from apps.common.http import client_ip

from .catalog import ALL_CODES
from .errors import MembershipInactive, OrganizationRequired, OrganizationSuspended
from .models import Membership, MembershipStore, Organization, Role, RolePermission

_CACHE_SECONDS = 60


@dataclass(frozen=True)
class RequestContext:
    user: User
    organization: Organization
    membership: Membership
    role: Role
    permissions: frozenset[str]
    store_ids: frozenset[uuid.UUID]  # empty when all_stores
    session_id: uuid.UUID
    mfa_verified: bool
    request_id: str
    ip_address: str | None
    user_agent: str

    @property
    def all_stores(self) -> bool:
        return self.membership.all_stores

    @property
    def is_owner(self) -> bool:
        return self.role.is_owner

    def has_perm(self, code: str) -> bool:
        return code in self.permissions

    def can_access_store(self, store_id: uuid.UUID) -> bool:
        return self.all_stores or store_id in self.store_ids

    @property
    def audit_actor(self) -> AuditActor:
        return AuditActor(
            organization_id=self.organization.pk,
            user_id=self.user.pk,
            request_id=self.request_id,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
        )


def get_request_context(request: Request) -> RequestContext:
    """Resolve (once per request) and return the caller's tenant context."""
    django_request = request._request
    cached: RequestContext | None = getattr(django_request, "_shopflow_ctx", None)
    if cached is not None:
        return cached

    user, claims = request.user, request.auth
    if not isinstance(user, User) or not isinstance(claims, AccessClaims):
        raise OrganizationRequired("Sign in to continue.")

    state = get_session_state(claims.session_id)
    if state is None or state.organization_id is None:
        raise OrganizationRequired("Choose a business to work in first.")

    membership = (
        Membership.unscoped.select_related("organization", "role")
        .filter(user=user, organization_id=state.organization_id)
        .first()
    )
    if membership is None or membership.status != Membership.Status.ACTIVE:
        raise MembershipInactive("Your access to this business has been suspended.")
    if membership.organization.status != Organization.Status.ACTIVE:
        raise OrganizationSuspended("This business account is suspended.")

    ctx = RequestContext(
        user=user,
        organization=membership.organization,
        membership=membership,
        role=membership.role,
        permissions=role_permissions(membership.role),
        store_ids=frozenset() if membership.all_stores else membership_store_ids(membership.pk),
        session_id=claims.session_id,
        mfa_verified=state.mfa_verified,
        request_id=getattr(django_request, "request_id", ""),
        ip_address=client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:256],
    )
    django_request._shopflow_ctx = ctx  # type: ignore[attr-defined]
    return ctx


def role_permissions(role: Role) -> frozenset[str]:
    if role.is_owner:
        return ALL_CODES
    key = _role_key(role.pk)
    cached = cache.get(key)
    if isinstance(cached, frozenset):
        return cached
    codes = frozenset(
        RolePermission.objects.filter(role_id=role.pk).values_list("permission_id", flat=True)
    )
    cache.set(key, codes, timeout=_CACHE_SECONDS)
    return codes


def membership_store_ids(membership_id: uuid.UUID) -> frozenset[uuid.UUID]:
    key = _stores_key(membership_id)
    cached = cache.get(key)
    if isinstance(cached, frozenset):
        return cached
    ids = frozenset(
        MembershipStore.objects.filter(membership_id=membership_id).values_list(
            "store_id", flat=True
        )
    )
    cache.set(key, ids, timeout=_CACHE_SECONDS)
    return ids


def invalidate_role(role_id: uuid.UUID) -> None:
    cache.delete(_role_key(role_id))


def invalidate_membership(membership_id: uuid.UUID) -> None:
    cache.delete(_stores_key(membership_id))


def _role_key(role_id: uuid.UUID) -> str:
    return f"authz:role:{role_id}:permissions"


def _stores_key(membership_id: uuid.UUID) -> str:
    return f"authz:membership:{membership_id}:stores"
