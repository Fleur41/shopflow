import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession
from apps.organizations.models import Membership
from apps.organizations.testing import PASSWORD, client_for, role

pytestmark = pytest.mark.django_db
LOGIN_URL = "/api/v1/auth/login/"


def _login(email, **extra):
    return APIClient().post(
        LOGIN_URL, {"email": email, "password": PASSWORD, "client": "mobile"} | extra
    )


def _bearer(body):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['tokens']['access_token']}")
    return client


@pytest.fixture
def two_business_user(biz, other_biz):
    """The cashier of Duka A also works at Duka B."""
    Membership.objects.create(
        organization=other_biz.organization,
        user=biz.cashier.user,
        role=role(other_biz.organization, "CASHIER"),
        all_stores=True,
    )
    return biz.cashier.user


def test_single_business_users_land_in_it(biz):
    response = _login(biz.user.email)

    assert response.status_code == 200
    assert AuthSession.objects.get().organization == biz.organization
    me = _bearer(response.json()).get("/api/v1/auth/me/").json()
    assert me["organization"]["id"] == str(biz.organization.pk)


def test_multi_business_users_must_choose(two_business_user, other_biz):
    body = _login(two_business_user.email).json()
    client = _bearer(body)

    me = client.get("/api/v1/auth/me/").json()
    assert me["organization"] is None
    assert len(me["organizations"]) == 2
    response = client.get("/api/v1/stores/")
    assert response.status_code == 403
    assert response.json()["code"] == "ORGANIZATION_REQUIRED"


def test_login_can_name_the_business(two_business_user, other_biz):
    response = _login(two_business_user.email, organization_id=str(other_biz.organization.pk))

    assert response.status_code == 200
    assert AuthSession.objects.get().organization == other_biz.organization


def test_login_into_a_business_you_dont_belong_to_is_refused(biz, other_biz):
    response = _login(biz.user.email, organization_id=str(other_biz.organization.pk))

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_A_MEMBER"
    assert not AuthSession.objects.exists()


def test_switching_business_starts_a_new_session_and_ends_the_old(
    two_business_user, biz, other_biz
):
    old = _login(two_business_user.email, organization_id=str(biz.organization.pk)).json()
    old_client = _bearer(old)

    response = old_client.post(
        "/api/v1/auth/switch-organization/", {"organization_id": str(other_biz.organization.pk)}
    )

    assert response.status_code == 200
    new_client = _bearer(response.json())
    assert new_client.get("/api/v1/organization/").json()["name"] == "Duka B"
    assert old_client.get("/api/v1/organization/").status_code == 401
    old_session = AuthSession.objects.get(pk=old["session"]["id"])
    assert old_session.revoke_reason == AuthSession.RevokeReason.SWITCHED_ORGANIZATION


def test_cannot_switch_into_a_business_you_dont_belong_to(biz, other_biz):
    client = client_for(biz.user, biz.organization)

    response = client.post(
        "/api/v1/auth/switch-organization/", {"organization_id": str(other_biz.organization.pk)}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_A_MEMBER"
    assert client.get("/api/v1/organization/").status_code == 200  # current session untouched
