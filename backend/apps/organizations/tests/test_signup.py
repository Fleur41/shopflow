import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession, User
from apps.audit.models import AuditLog
from apps.organizations.models import Membership, Organization, Role, Store

pytestmark = pytest.mark.django_db
SIGNUP_URL = "/api/v1/auth/signup/"
STRONG = "a-long-and-unusual-passphrase"


def _payload(**overrides):
    return {
        "email": "Wanjiku@Example.com",
        "full_name": "Wanjiku Kamau",
        "password": STRONG,
        "organization_name": "Mama Wanjiku Shop",
        "store_name": "Kawangware",
    } | overrides


@pytest.fixture
def browser():
    client = APIClient(enforce_csrf_checks=True)
    client.credentials(HTTP_X_CSRFTOKEN=client.get("/api/v1/auth/csrf/").json()["csrf_token"])
    return client


def test_signup_creates_owner_business_store_and_roles(browser):
    response = browser.post(SIGNUP_URL, _payload())

    assert response.status_code == 201
    assert "tokens" not in response.json()
    assert settings.AUTH_ACCESS_COOKIE_NAME in response.cookies
    user = User.objects.get(email="wanjiku@example.com")
    organization = Organization.objects.get()
    assert organization.base_currency == "KES"
    assert organization.timezone == "Africa/Nairobi"
    store = Store.objects.for_org(organization).get()
    assert (store.code, store.name, store.currency) == ("MAIN", "Kawangware", "KES")
    roles = set(Role.objects.for_org(organization).values_list("template", flat=True))
    assert roles == {"OWNER", "MANAGER", "CASHIER"}
    membership = Membership.objects.for_org(organization).get()
    assert (membership.user, membership.role.template, membership.all_stores) == (
        user,
        "OWNER",
        True,
    )
    assert AuthSession.objects.get().organization == organization
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert actions == {"organization.created", "store.created"}


def test_new_owner_is_immediately_working_in_their_business(browser):
    browser.post(SIGNUP_URL, _payload())

    me = browser.get("/api/v1/auth/me/").json()

    assert me["organization"]["name"] == "Mama Wanjiku Shop"
    assert me["access"]["role"]["template"] == "OWNER"
    assert "users.manage" in me["access"]["permissions"]
    assert [s["code"] for s in me["access"]["stores"]] == ["MAIN"]


def test_mobile_signup_returns_tokens():
    response = APIClient().post(
        SIGNUP_URL, _payload(client="mobile", currency="UGX", timezone="Africa/Kampala")
    )

    assert response.status_code == 201
    assert response.json()["tokens"]["access_token"]
    assert Organization.objects.get().base_currency == "UGX"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "password123"),
        ("currency", "kes"),
        ("timezone", "Mars/Olympus"),
        ("email", "not-an-email"),
    ],
)
def test_invalid_signups_are_rejected_without_side_effects(browser, field, value):
    response = browser.post(SIGNUP_URL, _payload(**{field: value}))

    assert response.status_code == 400
    assert f"/{field}" in {e["pointer"] for e in response.json()["errors"]}
    assert not User.objects.exists()
    assert not Organization.objects.exists()


def test_existing_email_cannot_sign_up_again(browser, biz):
    response = browser.post(SIGNUP_URL, _payload(email=biz.user.email))

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "TAKEN"


def test_web_signup_requires_csrf():
    response = APIClient(enforce_csrf_checks=True).post(SIGNUP_URL, _payload())

    assert response.status_code == 403
    assert not User.objects.exists()


def test_signup_is_atomic(browser, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("apps.organizations.services._create_default_roles", fail)
    client = APIClient(enforce_csrf_checks=True, raise_request_exception=False)
    client.cookies = browser.cookies
    client.credentials(**browser._credentials)

    response = client.post(SIGNUP_URL, _payload())

    assert response.status_code == 500
    assert not User.objects.exists()
    assert not Organization.objects.exists()
