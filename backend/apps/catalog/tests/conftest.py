from types import SimpleNamespace

import pytest

from apps.organizations.testing import add_staff, client_for, context_for, create_business


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
    return context_for(biz.membership)
