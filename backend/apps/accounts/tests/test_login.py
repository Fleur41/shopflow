from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.api.throttles import LoginEmailThrottle, LoginIPThrottle
from apps.accounts.models import AuthSession, User

from .conftest import LOGIN_URL, PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def no_throttles(monkeypatch):
    """Isolate lockout behaviour from the (lower) per-email rate limit."""
    for throttle in (LoginEmailThrottle, LoginIPThrottle):
        monkeypatch.setattr(throttle, "allow_request", lambda self, request, view: True)


def _login(**overrides):
    return (
        dict(
            email="cashier@example.com",
            password=PASSWORD,
            client_type=AuthSession.ClientType.WEB,
            ip_address="203.0.113.7",
            user_agent="pytest",
        )
        | overrides
    )


# --- Web sign-in -----------------------------------------------------------------


def test_web_login_sets_hardened_cookies_and_returns_no_tokens(web_client, user):
    response = web_client.post(LOGIN_URL, {"email": user.email, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert "tokens" not in body
    assert body["user"] == {
        "id": str(user.pk),
        "email": "cashier@example.com",
        "full_name": "Jane Cashier",
        "phone": "",
        "email_verified": False,
    }
    assert body["session"]["client_type"] == "WEB"

    access = response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]
    refresh = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
    assert access.key == "__Host-sf_at"
    assert refresh.key == "__Secure-sf_rt"
    for cookie in (access, refresh):
        assert cookie["httponly"]
        assert cookie["secure"]
    assert access["samesite"] == "Lax"
    assert access["path"] == "/"
    assert int(access["max-age"]) == 600
    assert refresh["samesite"] == "Strict"
    assert refresh["path"] == "/api/v1/auth/"
    assert int(refresh["max-age"]) == 14 * 24 * 3600


def test_web_login_requires_csrf_token(user):
    browser_without_token = APIClient(enforce_csrf_checks=True)

    response = browser_without_token.post(LOGIN_URL, {"email": user.email, "password": PASSWORD})

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert not AuthSession.objects.exists()


def test_mobile_login_returns_tokens_and_sets_no_cookies(user):
    response = APIClient().post(
        LOGIN_URL,
        {"email": user.email, "password": PASSWORD, "client": "mobile", "device_name": "Till 2"},
    )

    assert response.status_code == 200
    tokens = response.json()["tokens"]
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token"].count(".") == 2
    assert tokens["refresh_token"]
    assert not response.cookies
    session = AuthSession.objects.get()
    assert session.client_type == "MOBILE"
    assert session.device_name == "Till 2"
    assert session.expires_at - session.created_at >= timedelta(days=89)


def test_login_records_session_metadata_and_last_login(web_client, user):
    web_client.post(
        LOGIN_URL,
        {"email": "CASHIER@Example.com ", "password": PASSWORD},
        HTTP_USER_AGENT="Mozilla/5.0 POS",
    )

    session = AuthSession.objects.get()
    assert session.user == user
    assert session.user_agent == "Mozilla/5.0 POS"
    assert session.ip_address == "127.0.0.1"
    user.refresh_from_db()
    assert user.last_login is not None


# --- Failures never reveal whether an account exists ------------------------------


def test_wrong_password_unknown_email_and_inactive_user_look_identical(web_client, user):
    inactive = User.objects.create_user("gone@example.com", PASSWORD, full_name="Gone")
    inactive.is_active = False
    inactive.save()

    responses = [
        web_client.post(LOGIN_URL, {"email": user.email, "password": "wrong-password"}),
        web_client.post(LOGIN_URL, {"email": "nobody@example.com", "password": PASSWORD}),
        web_client.post(LOGIN_URL, {"email": inactive.email, "password": PASSWORD}),
    ]

    bodies = [(r.status_code, r.json()["code"], r.json()["detail"]) for r in responses]
    assert bodies == [(401, "INVALID_CREDENTIALS", "The email or password is incorrect.")] * 3
    assert not AuthSession.objects.exists()


def test_invalid_input_is_a_validation_error(web_client):
    response = web_client.post(LOGIN_URL, {"email": "not-an-email"})

    assert response.status_code == 400
    pointers = {error["pointer"] for error in response.json()["errors"]}
    assert pointers == {"/email", "/password"}


def test_passwords_never_reach_the_logs(web_client, user, caplog):
    wrong_guess = "hunter2-wrong-guess"
    web_client.post(LOGIN_URL, {"email": user.email, "password": wrong_guess})
    web_client.post(LOGIN_URL, {"email": user.email, "password": PASSWORD})

    logged = caplog.text + " ".join(str(record.msg) for record in caplog.records)
    assert wrong_guess not in logged
    assert PASSWORD not in logged
    assert "cashier@example.com" not in logged  # emails are logged only as fingerprints


# --- Brute-force protection ----------------------------------------------------------


def test_account_locks_after_ten_failures_even_for_the_right_password(user):
    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD):
        with pytest.raises(services.InvalidCredentials):
            services.login(**_login(password="wrong-password"))

    with pytest.raises(services.LoginTemporarilyLocked) as locked:
        services.login(**_login())

    assert locked.value.headers["Retry-After"] == "900"
    assert "15 minutes" in locked.value.detail


def test_unknown_emails_lock_the_same_way(db):
    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD):
        with pytest.raises(services.InvalidCredentials):
            services.login(**_login(email="nobody@example.com"))

    with pytest.raises(services.LoginTemporarilyLocked):
        services.login(**_login(email="nobody@example.com"))


def test_successful_login_resets_the_failure_count(user):
    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD - 1):
        with pytest.raises(services.InvalidCredentials):
            services.login(**_login(password="wrong-password"))
    services.login(**_login())

    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD - 1):
        with pytest.raises(services.InvalidCredentials):
            services.login(**_login(password="wrong-password"))
    services.login(**_login())  # still not locked


def test_lock_expires_after_fifteen_minutes(user):
    with time_machine.travel(timezone.now(), tick=False) as traveller:
        for _ in range(settings.AUTH_LOCKOUT_THRESHOLD):
            with pytest.raises(services.InvalidCredentials):
                services.login(**_login(password="wrong-password"))
        traveller.shift(timedelta(minutes=14))
        with pytest.raises(services.LoginTemporarilyLocked):
            services.login(**_login())
        traveller.shift(timedelta(minutes=1, seconds=1))
        assert services.login(**_login()).session.user == user


def test_lockout_response_over_http(web_client, user, no_throttles):
    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD):
        web_client.post(LOGIN_URL, {"email": user.email, "password": "wrong-password"})

    response = web_client.post(LOGIN_URL, {"email": user.email, "password": PASSWORD})

    assert response.status_code == 429
    assert response.json()["code"] == "LOGIN_TEMPORARILY_LOCKED"
    assert int(response["Retry-After"]) > 0


def test_per_email_rate_limit(web_client, user):
    for _ in range(5):
        web_client.post(LOGIN_URL, {"email": user.email, "password": "wrong-password"})

    response = web_client.post(LOGIN_URL, {"email": "Cashier@Example.com", "password": PASSWORD})

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert int(response["Retry-After"]) > 0


def test_per_ip_rate_limit_spans_accounts(web_client, user, monkeypatch):
    monkeypatch.setattr(LoginEmailThrottle, "allow_request", lambda self, request, view: True)
    for attempt in range(20):
        web_client.post(LOGIN_URL, {"email": f"user{attempt}@example.com", "password": "x"})

    response = web_client.post(LOGIN_URL, {"email": user.email, "password": PASSWORD})

    assert response.status_code == 429
