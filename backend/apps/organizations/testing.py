"""Test helpers for building businesses, staff and signed-in API clients.

Used by tests across apps; never imported by application code.
"""

from collections.abc import Iterable

from rest_framework.test import APIClient

from apps.accounts.models import AuthSession, User
from apps.accounts.services import start_session

from .models import Membership, MembershipStore, Organization, Role, Store
from .services import RegisteredBusiness, register_business

PASSWORD = "correct-horse-battery-staple"


def create_business(
    *, email: str = "owner@duka-a.example", name: str = "Duka A", currency: str = "KES"
) -> RegisteredBusiness:
    return register_business(
        email=email,
        full_name=f"Owner of {name}",
        password=PASSWORD,
        organization_name=name,
        currency=currency,
        timezone="Africa/Nairobi",
    )


def role(organization: Organization, template: str) -> Role:
    return Role.objects.for_org(organization).get(template=template)


def add_staff(
    organization: Organization,
    *,
    email: str,
    template: str = Role.Template.CASHIER,
    role_obj: Role | None = None,
    stores: Iterable[Store] = (),
    all_stores: bool = False,
) -> Membership:
    """Create a user with a membership directly (bypassing the API under test)."""
    user = User.objects.create_user(email, PASSWORD, full_name=email.split("@")[0].title())
    membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=role_obj or role(organization, template),
        all_stores=all_stores,
    )
    MembershipStore.objects.bulk_create(
        MembershipStore(membership=membership, store=store) for store in stores
    )
    return membership


def add_store(organization: Organization, code: str, name: str | None = None) -> Store:
    return Store.objects.create(
        organization=organization,
        code=code,
        name=name or f"Store {code}",
        currency=organization.base_currency,
        timezone=organization.timezone,
    )


def client_for(user: User, organization: Organization | None, *, mfa: bool = True) -> APIClient:
    """A Bearer-authenticated client whose session works in ``organization``.

    By default the session counts as MFA-verified, as after a real two-step
    sign-in; pass ``mfa=False`` to test enforcement.
    """
    issued = start_session(
        user=user,
        client_type=AuthSession.ClientType.MOBILE,
        organization_id=organization.pk if organization else None,
        ip_address=None,
        user_agent="pytest",
        mfa_verified=mfa,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access_token}")
    return client
