from types import SimpleNamespace

import pytest

from apps.organizations.catalog import CASHIER, ROLE_TEMPLATES
from apps.organizations.models import Role, RolePermission
from apps.organizations.testing import add_staff, add_store, client_for, create_business


@pytest.fixture
def biz(db):
    """Business A: an owner, a second store, and a cashier limited to the main store."""
    registered = create_business()
    return SimpleNamespace(
        user=registered.user,
        organization=registered.organization,
        store=registered.store,
        membership=registered.membership,
        branch=add_store(registered.organization, "BR2", "Branch 2"),
        cashier=add_staff(
            registered.organization, email="cashier@duka-a.example", stores=[registered.store]
        ),
    )


@pytest.fixture
def other_biz(db):
    return create_business(email="owner@duka-b.example", name="Duka B")


@pytest.fixture
def owner_client(biz):
    return client_for(biz.user, biz.organization)


@pytest.fixture
def cashier_client(biz):
    return client_for(biz.cashier.user, biz.organization)


@pytest.fixture
def manager(biz):
    return add_staff(
        biz.organization,
        email="manager@duka-a.example",
        template=Role.Template.MANAGER,
        stores=[biz.store],
    )


@pytest.fixture
def manager_client(biz, manager):
    return client_for(manager.user, biz.organization)


@pytest.fixture
def supervisor_client(biz):
    """May manage staff and sell, but only at the main store and without owner rights."""
    supervisor_role = Role.objects.create(
        organization=biz.organization, name="Supervisor", template=Role.Template.CUSTOM
    )
    RolePermission.objects.bulk_create(
        RolePermission(role=supervisor_role, permission_id=code)
        for code in ROLE_TEMPLATES[CASHIER][2] | {"users.view", "users.manage"}
    )
    supervisor = add_staff(
        biz.organization, email="sup@duka-a.example", role_obj=supervisor_role, stores=[biz.store]
    )
    return client_for(supervisor.user, biz.organization)
