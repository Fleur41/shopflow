import pytest

from apps.organizations.catalog import ALL_CODES
from apps.organizations.models import Role
from apps.organizations.testing import add_staff, client_for, role

pytestmark = pytest.mark.django_db


def test_role_list_shows_templates_and_owner_has_everything(owner_client):
    roles = {r["template"]: r for r in owner_client.get("/api/v1/roles/").json()["results"]}

    assert set(roles) == {"OWNER", "MANAGER", "CASHIER"}
    assert set(roles["OWNER"]["permissions"]) == ALL_CODES
    assert roles["OWNER"]["is_system"]


def test_permission_catalog_endpoint(owner_client):
    permissions = owner_client.get("/api/v1/permissions/").json()

    assert {p["code"] for p in permissions} == ALL_CODES
    assert next(p for p in permissions if p["code"] == "sales.void")["is_sensitive"]


def test_owner_creates_a_custom_role(owner_client):
    response = owner_client.post(
        "/api/v1/roles/",
        {"name": "Stock clerk", "permissions": ["inventory.view", "inventory.receive"]},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["template"] == "CUSTOM"
    assert response.json()["permissions"] == ["inventory.receive", "inventory.view"]


def test_unknown_permissions_and_duplicate_names_are_rejected(owner_client):
    unknown = owner_client.post(
        "/api/v1/roles/", {"name": "X", "permissions": ["sales.everything"]}, format="json"
    )
    duplicate = owner_client.post(
        "/api/v1/roles/", {"name": "cashier", "permissions": []}, format="json"
    )

    assert unknown.status_code == 400
    assert duplicate.status_code == 400
    assert duplicate.json()["errors"][0]["pointer"] == "/name"


def test_the_owner_role_cannot_be_edited(owner_client, biz):
    owner_role = role(biz.organization, Role.Template.OWNER)

    response = owner_client.patch(
        f"/api/v1/roles/{owner_role.pk}/", {"permissions": []}, format="json"
    )

    assert response.status_code == 422
    assert response.json()["code"] == "SYSTEM_ROLE_IMMUTABLE"


@pytest.fixture
def hr_client(owner_client, biz):
    """Someone who may manage roles, but holds few permissions themselves."""
    hr_role = Role.objects.for_org(biz.organization).get(
        pk=owner_client.post(
            "/api/v1/roles/",
            {"name": "HR", "permissions": ["roles.view", "roles.manage", "users.view"]},
            format="json",
        ).json()["id"]
    )
    hr = add_staff(biz.organization, email="hr@duka-a.example", role_obj=hr_role, all_stores=True)
    return client_for(hr.user, biz.organization)


def test_you_cannot_grant_permissions_you_do_not_hold(hr_client):
    response = hr_client.post(
        "/api/v1/roles/",
        {"name": "Sneaky", "permissions": ["users.view", "sales.void"]},
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["errors"][0]["meta"] == {"permissions": ["sales.void"]}


def test_you_cannot_edit_roles_more_powerful_than_yours(hr_client, biz):
    manager_role = role(biz.organization, Role.Template.MANAGER)

    response = hr_client.patch(f"/api/v1/roles/{manager_role.pk}/", {"name": "Boss"}, format="json")

    assert response.status_code == 403
    assert response.json()["code"] == "PRIVILEGE_ESCALATION"
