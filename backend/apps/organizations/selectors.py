"""Read queries for tenancy. Every query is scoped to the caller's organization."""

import uuid

from django.db.models import QuerySet

from apps.accounts.models import User

from .context import RequestContext
from .errors import NotAMember
from .models import Membership, Organization, Role, Store


def active_memberships(user: User) -> QuerySet[Membership]:
    return Membership.unscoped.filter(
        user=user,
        status=Membership.Status.ACTIVE,
        organization__status=Organization.Status.ACTIVE,
    )


def choose_login_organization(user: User, requested: uuid.UUID | None) -> uuid.UUID | None:
    """The business a new session works in.

    An explicit request must name one of the user's businesses. Otherwise a
    user with exactly one business gets it; users with several (or none)
    start without one and choose via ``/auth/switch-organization/``.
    """
    memberships = active_memberships(user)
    if requested is not None:
        require_active_membership(user, requested)
        return requested
    organization_ids = list(memberships.values_list("organization_id", flat=True)[:2])
    return organization_ids[0] if len(organization_ids) == 1 else None


def require_active_membership(user: User, organization_id: uuid.UUID) -> None:
    if not active_memberships(user).filter(organization_id=organization_id).exists():
        raise NotAMember("You don't have access to that business.")


def accessible_stores(ctx: RequestContext) -> QuerySet[Store]:
    stores = Store.objects.for_org(ctx.organization)
    if not ctx.all_stores:
        stores = stores.filter(pk__in=ctx.store_ids)
    return stores.order_by("code")


def members(ctx: RequestContext) -> QuerySet[Membership]:
    return (
        Membership.objects.for_org(ctx.organization)
        .select_related("user", "role")
        .prefetch_related("stores")
    )


def roles(ctx: RequestContext) -> QuerySet[Role]:
    return Role.objects.for_org(ctx.organization).prefetch_related("permissions")
