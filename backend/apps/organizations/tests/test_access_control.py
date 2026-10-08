"""Permission checks, store scoping and context status checks."""

import pytest
from rest_framework.test import APIClient

from apps.organizations.models import Membership, Organization, Role

pytestmark = pytest.mark.django_db


def test_cashier_can_view_but_not_change_the_business(cashier_client):
    assert cashier_client.get("/api/v1/organization/").status_code == 200

    response = cashier_client.patch("/api/v1/organization/", {"name": "Hijacked"})

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "PERMISSION_DENIED"
    assert body["errors"][0]["meta"] == {"permission": "org.manage"}


def test_cashier_cannot_list_staff_or_roles(cashier_client):
    assert cashier_client.get("/api/v1/members/").status_code == 403
    assert cashier_client.get("/api/v1/roles/").status_code == 403


def test_store_limited_staff_only_see_their_stores(cashier_client, biz):
    listed = [s["code"] for s in cashier_client.get("/api/v1/stores/").json()["results"]]

    assert listed == ["MAIN"]
    assert cashier_client.get(f"/api/v1/stores/{biz.store.pk}/").status_code == 200
    assert cashier_client.get(f"/api/v1/stores/{biz.branch.pk}/").status_code == 404


def test_methods_without_a_declared_permission_are_denied(owner_client, biz):
    response = owner_client.delete(f"/api/v1/stores/{biz.store.pk}/")

    assert response.status_code == 403
    assert response.json()["errors"][0]["meta"] == {"permission": "undeclared:DELETE"}


def test_suspended_membership_is_refused_even_with_a_live_session(cashier_client, biz):
    Membership.objects.for_org(biz.organization).filter(pk=biz.cashier.pk).update(
        status=Membership.Status.SUSPENDED
    )

    response = cashier_client.get("/api/v1/stores/")

    assert response.status_code == 403
    assert response.json()["code"] == "MEMBERSHIP_INACTIVE"


def test_suspended_business_is_refused(owner_client, biz):
    Organization.objects.filter(pk=biz.organization.pk).update(status=Organization.Status.SUSPENDED)

    response = owner_client.get("/api/v1/stores/")

    assert response.status_code == 403
    assert response.json()["code"] == "ORGANIZATION_SUSPENDED"


def test_role_changes_apply_on_the_next_request(owner_client, manager_client, biz):
    assert manager_client.get("/api/v1/members/").status_code == 200  # caches role permissions
    manager_role = Role.objects.for_org(biz.organization).get(template="MANAGER")
    detail = owner_client.get(f"/api/v1/roles/{manager_role.pk}/").json()
    remaining = [code for code in detail["permissions"] if code != "users.view"]

    assert (
        owner_client.patch(
            f"/api/v1/roles/{manager_role.pk}/", {"permissions": remaining}
        ).status_code
        == 200
    )

    assert manager_client.get("/api/v1/members/").status_code == 403


def test_tenant_endpoints_require_authentication(db):
    assert APIClient().get("/api/v1/stores/").status_code == 401
