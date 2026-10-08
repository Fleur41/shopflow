from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession, RefreshToken

from .conftest import LOGIN_URL, PASSWORD, mobile_login

pytestmark = pytest.mark.django_db
REFRESH_URL = "/api/v1/auth/refresh/"
ME_URL = "/api/v1/auth/me/"
GRACE = settings.AUTH_REFRESH_REUSE_GRACE


def _refresh_mobile(refresh_token: str):
    return APIClient().post(REFRESH_URL, {"refresh_token": refresh_token})


def _bearer(access_token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    return client


def test_mobile_refresh_rotates_both_tokens(user):
    first = mobile_login(APIClient(), user.email)["tokens"]

    response = _refresh_mobile(first["refresh_token"])

    assert response.status_code == 200
    second = response.json()["tokens"]
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]
    assert _bearer(second["access_token"]).get(ME_URL).status_code == 200
    assert RefreshToken.objects.filter(rotated_at__isnull=True).count() == 1


def test_reusing_a_rotated_token_revokes_the_whole_session(user, caplog):
    first = mobile_login(APIClient(), user.email)["tokens"]
    with time_machine.travel(timezone.now(), tick=False) as traveller:
        second = _refresh_mobile(first["refresh_token"]).json()["tokens"]
        traveller.shift(GRACE + timedelta(seconds=1))

        replay = _refresh_mobile(first["refresh_token"])  # attacker replays a stolen token

        assert replay.status_code == 401
        assert replay.json()["code"] == "SESSION_EXPIRED"
        session = AuthSession.objects.get()
        assert session.revoke_reason == AuthSession.RevokeReason.TOKEN_REUSE
        # The legitimate holder is signed out too: both copies are now useless.
        assert _refresh_mobile(second["refresh_token"]).status_code == 401
        assert _bearer(second["access_token"]).get(ME_URL).status_code == 401
    assert "auth.refresh_token_reuse_detected" in caplog.text


def test_reuse_within_the_grace_window_is_a_harmless_race(user):
    first = mobile_login(APIClient(), user.email)["tokens"]
    second = _refresh_mobile(first["refresh_token"]).json()["tokens"]

    concurrent = _refresh_mobile(first["refresh_token"])

    assert concurrent.status_code == 409
    assert concurrent.json()["code"] == "REFRESH_IN_PROGRESS"
    assert AuthSession.objects.get().revoked_at is None
    assert _refresh_mobile(second["refresh_token"]).status_code == 200


def test_unknown_refresh_token_is_rejected(db):
    response = _refresh_mobile("made-up-token")

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


def test_idle_refresh_token_expires(user):
    with time_machine.travel(timezone.now(), tick=False) as traveller:
        tokens = mobile_login(APIClient(), user.email)["tokens"]
        traveller.shift(settings.AUTH_MOBILE_REFRESH_IDLE_LIFETIME + timedelta(seconds=1))

        assert _refresh_mobile(tokens["refresh_token"]).status_code == 401


def test_refresh_never_extends_past_the_absolute_session_lifetime(web_client, user):
    with time_machine.travel(timezone.now(), tick=False) as traveller:
        web_client.post(LOGIN_URL, {"email": user.email, "password": PASSWORD})
        session = AuthSession.objects.get()
        for _ in range(3):  # stay active: refresh every 10 days
            traveller.shift(timedelta(days=10))
            response = web_client.post(REFRESH_URL)
            if response.status_code != 200:
                break
            refresh_expiry = response.json()["session"]["refresh_expires_at"]
            assert refresh_expiry <= session.expires_at.isoformat().replace("+00:00", "Z")

        # Day 30: the absolute 30-day web session limit has been reached.
        assert response.status_code == 401
        assert response.json()["code"] == "SESSION_EXPIRED"


def test_web_refresh_uses_the_cookie_and_rotates_it(signed_in_web_client):
    old_cookie = signed_in_web_client.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value

    response = signed_in_web_client.post(REFRESH_URL)

    assert response.status_code == 200
    assert "tokens" not in response.json()
    new_cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value
    assert new_cookie != old_cookie
    assert signed_in_web_client.get(ME_URL).status_code == 200


def test_web_refresh_requires_csrf(signed_in_web_client):
    signed_in_web_client.credentials()

    response = signed_in_web_client.post(REFRESH_URL)

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"


def test_web_refresh_without_cookie_clears_cookies(web_client):
    response = web_client.post(REFRESH_URL)

    assert response.status_code == 401
    assert response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["max-age"] == 0
    assert response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["max-age"] == 0


def test_mobile_refresh_token_cannot_be_used_as_a_web_cookie(web_client, user):
    mobile_tokens = mobile_login(APIClient(), user.email)["tokens"]
    web_client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = mobile_tokens["refresh_token"]

    assert web_client.post(REFRESH_URL).status_code == 401


def test_deactivated_user_cannot_refresh(user):
    tokens = mobile_login(APIClient(), user.email)["tokens"]
    user.is_active = False
    user.save()

    assert _refresh_mobile(tokens["refresh_token"]).status_code == 401


def test_refresh_after_logout_fails(mobile_session):
    client, body = mobile_session
    client.post("/api/v1/auth/logout/")

    assert _refresh_mobile(body["tokens"]["refresh_token"]).status_code == 401
