from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession

pytestmark = pytest.mark.django_db
ME_URL = "/api/v1/auth/me/"


def test_bearer_token_authenticates(mobile_session, user):
    client, _ = mobile_session

    response = client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_cookie_authenticates_safe_requests_without_csrf_header(signed_in_web_client):
    signed_in_web_client.credentials()  # drop the X-CSRFToken header

    assert signed_in_web_client.get(ME_URL).status_code == 200


def test_cookie_authenticated_unsafe_requests_require_csrf(signed_in_web_client):
    signed_in_web_client.credentials()  # a cross-site form post would carry cookies only

    response = signed_in_web_client.post("/api/v1/auth/logout/")

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert AuthSession.objects.get().revoked_at is None


def test_anonymous_requests_get_401_with_bearer_challenge():
    response = APIClient().get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'


def test_expired_access_token_returns_token_expired(user):
    client = APIClient()
    with time_machine.travel(timezone.now(), tick=False) as traveller:
        from .conftest import mobile_login

        body = mobile_login(client, user.email)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['tokens']['access_token']}")
        traveller.shift(settings.AUTH_ACCESS_TOKEN_LIFETIME + timedelta(seconds=11))

        response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


@pytest.mark.parametrize(
    "header",
    ["Bearer not-a-jwt", "Bearer ", "Bearer a.b.c extra"],
)
def test_malformed_bearer_tokens_are_rejected(header):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=header)

    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"


def test_other_authorization_schemes_are_ignored(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Basic Y2FzaGllcjpwYXNz")

    assert client.get(ME_URL).status_code == 401


def test_revoked_session_is_rejected_on_the_very_next_request(mobile_session):
    client, _ = mobile_session
    assert client.get(ME_URL).status_code == 200  # warms the session cache

    assert client.post("/api/v1/auth/logout/").status_code == 204
    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_REVOKED"


def test_deactivated_user_is_rejected_immediately(mobile_session, user):
    client, _ = mobile_session
    user.is_active = False
    user.save()

    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_REVOKED"


def test_session_past_its_absolute_expiry_is_rejected(mobile_session):
    client, _ = mobile_session
    AuthSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_REVOKED"


def test_cached_session_state_saves_a_query_per_request(mobile_session, django_assert_num_queries):
    client, _ = mobile_session
    client.get(ME_URL)  # first request populates the cache

    with django_assert_num_queries(1):  # only the user lookup
        assert client.get(ME_URL).status_code == 200
