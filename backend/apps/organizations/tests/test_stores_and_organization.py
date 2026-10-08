import pytest

from apps.audit.models import AuditLog
from apps.organizations.models import Store

pytestmark = pytest.mark.django_db


def test_owner_creates_a_store_with_business_defaults(owner_client, biz):
    response = owner_client.post(
        "/api/v1/stores/", {"code": "gik1", "name": "Gikomba", "phone": "+254700000001"}
    )

    assert response.status_code == 201, response.json()["errors"]
    body = response.json()
    assert (body["code"], body["currency"], body["timezone"]) == ("GIK1", "KES", "Africa/Nairobi")
    entry = AuditLog.objects.get(action="store.created", entity_id=body["id"])
    assert entry.actor == biz.user
    assert entry.changes["code"] == [None, "GIK1"]


@pytest.mark.parametrize("code", ["main", "A", "TOO-LONG-CODE", "sp ace"])
def test_store_codes_must_be_unique_and_well_formed(owner_client, code):
    response = owner_client.post("/api/v1/stores/", {"code": code, "name": "X"})

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/code"


def test_store_updates_are_audited_and_code_and_currency_are_fixed(owner_client, biz):
    response = owner_client.patch(
        f"/api/v1/stores/{biz.store.pk}/",
        {"name": "Main shop", "code": "NEW", "currency": "USD", "is_active": False},
    )

    assert response.status_code == 200
    store = Store.objects.for_org(biz.organization).get(pk=biz.store.pk)
    assert (store.name, store.code, store.currency, store.is_active) == (
        "Main shop",
        "MAIN",
        "KES",
        False,
    )
    entry = AuditLog.objects.get(action="store.updated")
    assert entry.changes == {"is_active": [True, False], "name": ["Main store", "Main shop"]}


def test_managers_cannot_create_stores(manager_client):
    assert manager_client.post("/api/v1/stores/", {"code": "M2", "name": "X"}).status_code == 403


def test_owner_renames_the_business_but_cannot_change_its_currency(owner_client, biz):
    response = owner_client.patch(
        "/api/v1/organization/", {"name": "Duka A Ltd", "base_currency": "USD"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Duka A Ltd"
    assert response.json()["base_currency"] == "KES"
    assert AuditLog.objects.get(action="organization.updated").changes == {
        "name": ["Duka A", "Duka A Ltd"]
    }
