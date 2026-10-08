import re
from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.models import AuthSession, User
from apps.organizations.testing import PASSWORD, client_for, create_business

pytestmark = pytest.mark.django_db
NEW_PASSWORD = "a-brand-new-shop-password"


def _token(message):
    match = re.search(r"\?token=([A-Za-z0-9_-]+)", message.body)
    assert match, message.body
    return match.group(1)


# --- Email verification ------------------------------------------------------------


def test_signup_sends_a_verification_link(mailoutbox, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        APIClient().post(
            "/api/v1/auth/signup/",
            {
                "email": "new@duka.example", "full_name": "New Owner", "password": PASSWORD,
                "organization_name": "Duka", "client": "mobile",
            },
        )  # fmt: skip

    (message,) = mailoutbox
    assert message.to == ["new@duka.example"]
    assert f"{settings.FRONTEND_URL}/verify-email?token=" in message.body

    first = APIClient().post("/api/v1/auth/email/verify/", {"token": _token(message)})
    again = APIClient().post("/api/v1/auth/email/verify/", {"token": _token(message)})

    assert first.status_code == 200
    assert User.objects.get(email="new@duka.example").email_verified_at is not None
    assert again.status_code == 400
    assert again.json()["code"] == "TOKEN_INVALID"


def test_resending_verification_invalidates_the_previous_link(
    mailoutbox, django_capture_on_commit_callbacks
):
    business = create_business()
    client = client_for(business.user, business.organization)
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/api/v1/auth/email/verification/")
        client.post("/api/v1/auth/email/verification/")

    old, new = (_token(m) for m in mailoutbox)
    assert APIClient().post("/api/v1/auth/email/verify/", {"token": old}).status_code == 400
    assert APIClient().post("/api/v1/auth/email/verify/", {"token": new}).status_code == 200


def test_verification_links_expire(mailoutbox, django_capture_on_commit_callbacks):
    business = create_business()
    with django_capture_on_commit_callbacks(execute=True):
        client_for(business.user, business.organization).post("/api/v1/auth/email/verification/")

    with time_machine.travel(timezone.now() + timedelta(hours=24, seconds=1)):
        response = APIClient().post("/api/v1/auth/email/verify/", {"token": _token(mailoutbox[0])})

    assert response.status_code == 400


# --- Password reset -------------------------------------------------------------------


@pytest.fixture
def owner():
    return create_business().user


def _request_reset(email, capture):
    with capture(execute=True):
        return APIClient().post("/api/v1/auth/password/reset/", {"email": email})


def test_reset_request_looks_the_same_for_unknown_emails(
    owner, mailoutbox, django_capture_on_commit_callbacks
):
    unknown = _request_reset("nobody@example.com", django_capture_on_commit_callbacks)
    known = _request_reset(owner.email, django_capture_on_commit_callbacks)

    assert unknown.status_code == known.status_code == 202
    assert unknown.content == known.content
    assert [m.to for m in mailoutbox] == [[owner.email]]


def test_reset_sets_the_password_and_ends_every_session(
    owner, mailoutbox, django_capture_on_commit_callbacks
):
    signed_in = client_for(owner, None)
    _request_reset(owner.email, django_capture_on_commit_callbacks)
    token = _token(mailoutbox[0])

    weak = APIClient().post(
        "/api/v1/auth/password/reset/confirm/", {"token": token, "new_password": "123"}
    )
    assert weak.status_code == 400  # the link still works after a rejected password
    with django_capture_on_commit_callbacks(execute=True):
        ok = APIClient().post(
            "/api/v1/auth/password/reset/confirm/", {"token": token, "new_password": NEW_PASSWORD}
        )
    reused = APIClient().post(
        "/api/v1/auth/password/reset/confirm/", {"token": token, "new_password": NEW_PASSWORD + "!"}
    )

    assert ok.status_code == 200
    assert reused.status_code == 400
    owner.refresh_from_db()
    assert owner.check_password(NEW_PASSWORD)
    assert signed_in.get("/api/v1/auth/me/").status_code == 401
    assert mailoutbox[-1].subject == "ShopFlow security notice: Your password was reset"


def test_a_new_reset_link_replaces_the_old_one(
    owner, mailoutbox, django_capture_on_commit_callbacks
):
    _request_reset(owner.email, django_capture_on_commit_callbacks)
    _request_reset(owner.email, django_capture_on_commit_callbacks)
    old, new = (_token(m) for m in mailoutbox)

    payload = {"new_password": NEW_PASSWORD}
    assert (
        APIClient()
        .post("/api/v1/auth/password/reset/confirm/", {"token": old, **payload})
        .status_code
        == 400
    )
    assert (
        APIClient()
        .post("/api/v1/auth/password/reset/confirm/", {"token": new, **payload})
        .status_code
        == 200
    )


def test_reset_links_expire_after_thirty_minutes(
    owner, mailoutbox, django_capture_on_commit_callbacks
):
    _request_reset(owner.email, django_capture_on_commit_callbacks)

    with time_machine.travel(timezone.now() + timedelta(minutes=30, seconds=1)):
        response = APIClient().post(
            "/api/v1/auth/password/reset/confirm/",
            {"token": _token(mailoutbox[0]), "new_password": NEW_PASSWORD},
        )

    assert response.status_code == 400


def test_reset_lifts_a_lockout(owner, mailoutbox, django_capture_on_commit_callbacks):
    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD):
        with pytest.raises(services.InvalidCredentials):
            services.login(
                email=owner.email,
                password="wrong",
                client_type="MOBILE",
                ip_address=None,
                user_agent="",
            )
    _request_reset(owner.email, django_capture_on_commit_callbacks)
    APIClient().post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": _token(mailoutbox[0]), "new_password": NEW_PASSWORD},
    )

    issued = services.login(
        email=owner.email,
        password=NEW_PASSWORD,
        client_type="MOBILE",
        ip_address=None,
        user_agent="",
    )
    assert issued.session.user == owner


def test_reset_requests_are_rate_limited_per_email(owner, django_capture_on_commit_callbacks):
    for _ in range(3):
        _request_reset(owner.email, django_capture_on_commit_callbacks)

    assert _request_reset(owner.email, django_capture_on_commit_callbacks).status_code == 429


# --- Password change ------------------------------------------------------------------


def test_change_password_keeps_this_session_and_ends_the_others(
    owner, mailoutbox, django_capture_on_commit_callbacks
):
    current = client_for(owner, None)
    other = client_for(owner, None)

    wrong = current.post(
        "/api/v1/auth/password/change/", {"current_password": "nope", "new_password": NEW_PASSWORD}
    )
    with django_capture_on_commit_callbacks(execute=True):
        ok = current.post(
            "/api/v1/auth/password/change/",
            {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )

    assert wrong.status_code == 400
    assert wrong.json()["errors"][0]["pointer"] == "/current_password"
    assert ok.status_code == 204
    assert current.get("/api/v1/auth/me/").status_code == 200
    assert other.get("/api/v1/auth/me/").status_code == 401
    assert AuthSession.objects.filter(revoke_reason="PASSWORD_CHANGED").count() == 1
    assert mailoutbox[-1].subject == "ShopFlow security notice: Your password was changed"
