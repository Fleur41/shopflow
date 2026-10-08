import pytest

from apps.organizations.catalog import ALL_CODES, CASHIER, CATALOG, MANAGER, ROLE_TEMPLATES
from apps.organizations.context import role_permissions
from apps.organizations.models import Permission, Role, RolePermission
from apps.organizations.permission_sync import sync_permission_catalog
from apps.organizations.testing import role

pytestmark = pytest.mark.django_db


def test_catalog_is_synced_after_migrate():
    rows = {p.code: p for p in Permission.objects.all()}

    assert set(rows) == ALL_CODES
    assert all(rows[d.code].is_sensitive == d.sensitive for d in CATALOG)
    assert rows["sales.void"].category == "sales"


def test_new_business_gets_owner_manager_and_cashier_roles(biz):
    owner = role(biz.organization, Role.Template.OWNER)

    assert owner.is_system
    assert role_permissions(owner) == ALL_CODES
    assert role_permissions(role(biz.organization, MANAGER)) == ROLE_TEMPLATES[MANAGER][2]
    assert role_permissions(role(biz.organization, CASHIER)) == ROLE_TEMPLATES[CASHIER][2]


def test_sync_is_idempotent(biz):
    before = RolePermission.objects.count()

    sync_permission_catalog()
    sync_permission_catalog()

    assert RolePermission.objects.count() == before


def test_newly_introduced_codes_reach_existing_template_roles(biz):
    # Simulate a release that introduces "sales.void" (Manager template only).
    Permission.objects.filter(code="sales.void").delete()
    manager, cashier = role(biz.organization, MANAGER), role(biz.organization, CASHIER)
    assert not RolePermission.objects.filter(role=manager, permission_id="sales.void").exists()

    sync_permission_catalog()

    assert RolePermission.objects.filter(role=manager, permission_id="sales.void").exists()
    assert not RolePermission.objects.filter(role=cashier, permission_id="sales.void").exists()


def test_codes_removed_from_the_catalog_are_deleted(biz):
    Permission.objects.create(code="legacy.thing", description="Old", category="legacy")
    RolePermission.objects.create(
        role=role(biz.organization, MANAGER), permission_id="legacy.thing"
    )

    sync_permission_catalog()

    assert not Permission.objects.filter(code="legacy.thing").exists()
    assert not RolePermission.objects.filter(permission_id="legacy.thing").exists()
