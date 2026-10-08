import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.accounts.models import AuthSession, User

from .conftest import PASSWORD, mobile_login

pytestmark = pytest.mark.django_db
SESSIONS_URL = "/api/v1/auth/sessions/"
ME_URL = "/api/v1/auth/me/"


def _bearer(access_token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    return client


def test_logout_revokes_session_and_clears_cookies(signed_in_web_client):
    response = signed_in_web_client.post("/api/v1/auth/logout/")

    assert response.status_code == 204
    assert response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["max-age"] == 0
    assert response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]["max-age"] == 0
    session = AuthSession.objects.get()
    assert session.revoke_reason == AuthSession.RevokeReason.LOGOUT


def test_logout_all_ends_every_session(signed_in_web_client, user):
    phone = mobile_login(APIClient(), user.email)["tokens"]

    assert signed_in_web_client.post("/api/v1/auth/logout-all/").status_code == 204

    assert not AuthSession.objects.filter(revoked_at__isnull=True).exists()
    assert _bearer(phone["access_token"]).get(ME_URL).status_code == 401


def test_session_list_shows_only_active_sessions_and_marks_current(mobile_session, user):
    client, body = mobile_session
    other = mobile_login(APIClient(), user.email)["tokens"]
    ended = mobile_login(APIClient(), user.email)["tokens"]
    _bearer(ended["access_token"]).post("/api/v1/auth/logout/")

    response = client.get(SESSIONS_URL)

    assert response.status_code == 200
    sessions = response.json()["results"]
    assert len(sessions) == 2
    current = [s for s in sessions if s["current"]]
    assert [s["id"] for s in current] == [body["session"]["id"]]
    assert {s["device_name"] for s in sessions} == {"Till 2"}
    assert other  # the second active session is listed but not current


def test_user_can_revoke_another_of_their_sessions(mobile_session, user):
    client, _ = mobile_session
    stolen_phone = mobile_login(APIClient(), user.email)
    session_id = stolen_phone["session"]["id"]

    response = client.delete(f"{SESSIONS_URL}{session_id}/")

    assert response.status_code == 204
    assert not response.cookies  # not the current session: cookies untouched
    assert _bearer(stolen_phone["tokens"]["access_token"]).get(ME_URL).status_code == 401
    assert client.get(ME_URL).status_code == 200


def test_revoking_the_current_session_clears_cookies(signed_in_web_client):
    session_id = AuthSession.objects.get().pk

    response = signed_in_web_client.delete(f"{SESSIONS_URL}{session_id}/")

    assert response.status_code == 204
    assert response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]["max-age"] == 0


def test_users_cannot_see_or_revoke_other_users_sessions(mobile_session):
    client, _ = mobile_session
    intruder = User.objects.create_user("other@example.com", PASSWORD, full_name="Other")
    victim_session = mobile_login(APIClient(), intruder.email)["session"]["id"]

    listed = {s["id"] for s in client.get(SESSIONS_URL).json()["results"]}
    response = client.delete(f"{SESSIONS_URL}{victim_session}/")

    assert victim_session not in listed
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert AuthSession.objects.get(pk=victim_session).revoked_at is None


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", ME_URL),
        ("get", SESSIONS_URL),
        ("post", "/api/v1/auth/logout/"),
        ("post", "/api/v1/auth/logout-all/"),
    ],
)
def test_session_endpoints_require_authentication(method, url):
    response = getattr(APIClient(), method)(url)

    assert response.status_code == 401


def test_revocation_clears_the_session_cache_again_after_commit(
    mobile_session, django_capture_on_commit_callbacks
):
    from django.core.cache import cache

    from apps.accounts import services

    client, _ = mobile_session
    client.get(ME_URL)  # cache the active state
    session_id = AuthSession.objects.get().pk
    key = f"auth:session:v3:{session_id}"

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        services.logout(session_id=session_id)
    client.get(ME_URL)  # a request between revocation and commit re-populates the cache...
    assert cache.get(key) is not None
    for callback in callbacks:  # ...and the post-commit delete removes it
        callback()

    assert cache.get(key) is None
    assert client.get(ME_URL).status_code == 401
