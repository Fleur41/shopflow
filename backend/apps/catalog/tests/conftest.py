from types import SimpleNamespace

import pytest

from apps.organizations.context import RequestContext, role_permissions
from apps.organizations.models import Role
from apps.organizations.testing import add_staff, client_for, create_business, role


@pytest.fixture
def biz(db):
    registered = create_business()
    return SimpleNamespace(
        user=registered.user,
        organization=registered.organization,
        membership=registered.membership,
        cashier=add_staff(
            registered.organization, email="cashier@duka-a.example", stores=[registered.store]
        ),
    )


@pytest.fixture
def owner_client(biz):
    return client_for(biz.user, biz.organization)


@pytest.fixture
def cashier_client(biz):
    return client_for(biz.cashier.user, biz.organization)


@pytest.fixture
def owner_ctx(biz):
    """The owner's context, for calling services directly."""
    owner_role = role(biz.organization, Role.Template.OWNER)
    return RequestContext(
        user=biz.user,
        organization=biz.organization,
        membership=biz.membership,
        role=owner_role,
        permissions=role_permissions(owner_role),
        store_ids=frozenset(),
        session_id=biz.membership.pk,
        mfa_verified=True,
        request_id="",
        ip_address=None,
        user_agent="",
    )
