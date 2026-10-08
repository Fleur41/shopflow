import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.organizations import services
from apps.organizations.context import RequestContext
from apps.organizations.errors import LastOwner
from apps.organizations.models import Membership, Role
from apps.organizations.testing import PASSWORD, add_staff, role

pytestmark = pytest.mark.django_db
NEW_PASSWORD = "temporary-till-password-42"


def _new_member(biz, **overrides):
    return {
        "email": "Akinyi@Duka-A.example",
        "full_name": "Akinyi Otieno",
        "password": NEW_PASSWORD,
        "role_id": str(role(biz.organization, "CASHIER").pk),
        "store_ids": [str(biz.branch.pk)],
    } | overrides


def test_owner_adds_a_cashier_who_can_sign_in_to_their_store_only(owner_client, biz):
    response = owner_client.post("/api/v1/members/", _new_member(biz), format="json")

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "akinyi@duka-a.example"
    assert [s["code"] for s in body["stores"]] == ["BR2"]
    login = APIClient().post(
        "/api/v1/auth/login/",
        {"email": "akinyi@duka-a.example", "password": NEW_PASSWORD, "client": "mobile"},
    )
    assert login.status_code == 200
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['tokens']['access_token']}")
    assert [s["code"] for s in client.get("/api/v1/stores/").json()["results"]] == ["BR2"]
    entry = AuditLog.objects.get(action="membership.added")
    assert entry.changes["role"] == [None, "Cashier"]
    assert NEW_PASSWORD not in str(entry.changes)


def test_existing_accounts_cannot_be_added_without_invitations(owner_client, biz, other_biz):
    response = owner_client.post(
        "/api/v1/members/", _new_member(biz, email=other_biz.user.email), format="json"
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "ACCOUNT_EXISTS"


@pytest.mark.parametrize("field", ["role_id", "store_ids"])
def test_ids_from_another_business_are_unknown(owner_client, biz, other_biz, field):
    foreign = {
        "role_id": str(role(other_biz.organization, "CASHIER").pk),
        "store_ids": [str(other_biz.store.pk)],
    }[field]

    response = owner_client.post(
        "/api/v1/members/", _new_member(biz, **{field: foreign}), format="json"
    )

    assert response.status_code == 400
    error = response.json()["errors"][0]
    assert error["pointer"].startswith(f"/{field}")
    assert error["code"] == "DOES_NOT_EXIST"


def test_members_need_at_least_one_store(owner_client, biz):
    response = owner_client.post("/api/v1/members/", _new_member(biz, store_ids=[]), format="json")

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/store_ids"


def test_managers_have_view_only_access_to_staff(manager_client, biz):
    assert manager_client.get("/api/v1/members/").status_code == 200
    assert (
        manager_client.post("/api/v1/members/", _new_member(biz), format="json").status_code == 403
    )


def test_staff_managers_cannot_make_owners(supervisor_client, biz):
    response = supervisor_client.post(
        "/api/v1/members/",
        _new_member(biz, role_id=str(role(biz.organization, "OWNER").pk)),
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PRIVILEGE_ESCALATION"


def test_staff_managers_cannot_assign_roles_stronger_than_their_own(supervisor_client, biz):
    response = supervisor_client.post(
        "/api/v1/members/",
        _new_member(biz, role_id=str(role(biz.organization, "MANAGER").pk)),
        format="json",
    )

    assert response.status_code == 403
    assert "sales.void" in response.json()["errors"][0]["meta"]["permissions"]


def test_store_limited_staff_managers_cannot_grant_other_stores(supervisor_client, biz):
    other_store = supervisor_client.post(
        "/api/v1/members/", _new_member(biz, store_ids=[str(biz.branch.pk)]), format="json"
    )
    everywhere = supervisor_client.post(
        "/api/v1/members/", _new_member(biz, all_stores=True, store_ids=[]), format="json"
    )

    assert other_store.status_code == 403
    assert everywhere.status_code == 403
    allowed = supervisor_client.post(
        "/api/v1/members/", _new_member(biz, store_ids=[str(biz.store.pk)]), format="json"
    )
    assert allowed.status_code == 201


def test_staff_managers_cannot_manage_owners(supervisor_client, biz):
    response = supervisor_client.post(
        f"/api/v1/members/{biz.membership.pk}/suspend/", {"reason": "coup"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PRIVILEGE_ESCALATION"


def test_nobody_can_change_their_own_access(owner_client, biz):
    response = owner_client.patch(
        f"/api/v1/members/{biz.membership.pk}/",
        {"version": 1, "role_id": str(role(biz.organization, "CASHIER").pk)},
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CANNOT_MODIFY_SELF"


def test_member_updates_use_optimistic_versioning(owner_client, biz):
    url = f"/api/v1/members/{biz.cashier.pk}/"
    payload = {"version": 1, "store_ids": [str(biz.store.pk), str(biz.branch.pk)]}

    first = owner_client.patch(url, payload, format="json")
    stale = owner_client.patch(url, payload | {"all_stores": True}, format="json")

    assert first.status_code == 200
    assert first.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_VERSION"


def test_store_changes_apply_on_the_next_request(owner_client, cashier_client, biz):
    assert cashier_client.get(f"/api/v1/stores/{biz.branch.pk}/").status_code == 404

    owner_client.patch(
        f"/api/v1/members/{biz.cashier.pk}/",
        {"version": 1, "store_ids": [str(biz.store.pk), str(biz.branch.pk)]},
        format="json",
    )

    assert cashier_client.get(f"/api/v1/stores/{biz.branch.pk}/").status_code == 200


def test_suspension_ends_sessions_immediately_and_is_audited(owner_client, cashier_client, biz):
    assert cashier_client.get("/api/v1/stores/").status_code == 200

    response = owner_client.post(
        f"/api/v1/members/{biz.cashier.pk}/suspend/", {"reason": "Cash shortage under review"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "SUSPENDED"
    assert cashier_client.get("/api/v1/stores/").status_code == 401
    login = APIClient().post(
        "/api/v1/auth/login/",
        {"email": biz.cashier.user.email, "password": PASSWORD, "client": "mobile"},
    )
    assert login.status_code == 200  # the account itself still works...
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['tokens']['access_token']}")
    assert client.get("/api/v1/stores/").status_code == 403  # ...but not in this business
    entry = AuditLog.objects.get(action="membership.suspended")
    assert entry.reason == "Cash shortage under review"


def test_suspension_requires_a_reason(owner_client, biz):
    response = owner_client.post(f"/api/v1/members/{biz.cashier.pk}/suspend/", {})

    assert response.status_code == 400


def test_reactivation_restores_access(owner_client, biz):
    owner_client.post(f"/api/v1/members/{biz.cashier.pk}/suspend/", {"reason": "Leave"})

    response = owner_client.post(f"/api/v1/members/{biz.cashier.pk}/reactivate/")

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"


def test_owners_can_demote_other_owners(owner_client, biz):
    co_owner = add_staff(
        biz.organization, email="co@duka-a.example", template="OWNER", all_stores=True
    )

    response = owner_client.patch(
        f"/api/v1/members/{co_owner.pk}/",
        {"version": 1, "role_id": str(role(biz.organization, "MANAGER").pk)},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["role"]["template"] == "MANAGER"


def test_last_active_owner_cannot_be_removed_even_in_a_race(biz, owner_client):
    """Owner A suspends owner B while A's own access was concurrently suspended."""
    co_owner = add_staff(
        biz.organization, email="co@duka-a.example", template="OWNER", all_stores=True
    )
    owner_client.get("/api/v1/organization/")  # build a real context for owner A
    from apps.organizations.context import role_permissions

    ctx = RequestContext(
        user=biz.user,
        organization=biz.organization,
        membership=biz.membership,
        role=role(biz.organization, Role.Template.OWNER),
        permissions=role_permissions(role(biz.organization, Role.Template.OWNER)),
        store_ids=frozenset(),
        session_id=biz.membership.pk,
        mfa_verified=True,
        request_id="",
        ip_address=None,
        user_agent="",
    )
    Membership.objects.for_org(biz.organization).filter(pk=biz.membership.pk).update(
        status=Membership.Status.SUSPENDED
    )

    with pytest.raises(LastOwner):
        services.suspend_member(ctx, co_owner, reason="race")
