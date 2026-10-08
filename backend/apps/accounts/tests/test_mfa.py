import time
from datetime import timedelta

import pyotp
import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import mfa
from apps.accounts.models import AuthSession, RecoveryCode, TOTPDevice
from apps.organizations.testing import PASSWORD, client_for, create_business

pytestmark = pytest.mark.django_db
LOGIN = "/api/v1/auth/login/"
VERIFY = "/api/v1/auth/mfa/verify/"


# --- Codes and secrets --------------------------------------------------------


def test_codes_are_accepted_with_one_step_of_clock_drift_only():
    secret = mfa.new_secret()
    totp = pyotp.TOTP(secret)
    now = int(time.time())

    for offset in (-30, 0, 30):
        assert mfa.matching_step(secret, totp.at(now + offset), after_step=None) is not None
    for offset in (-90, 90):
        assert mfa.matching_step(secret, totp.at(now + offset), after_step=None) is None


def test_a_used_code_is_never_accepted_again():
    secret = mfa.new_secret()
    code = pyotp.TOTP(secret).now()
    step = mfa.matching_step(secret, code, after_step=None)

    assert mfa.matching_step(secret, code, after_step=step) is None


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", "12 34 5x"])
def test_malformed_codes_are_rejected(code):
    assert mfa.matching_step(mfa.new_secret(), code, after_step=None) is None


def test_secrets_are_encrypted_and_keys_can_rotate(settings):
    token = mfa.encrypt_secret("JBSWY3DPEHPK3PXP")
    assert "JBSWY3DPEHPK3PXP" not in token

    old_key = settings.MFA_ENCRYPTION_KEYS[0]
    settings.MFA_ENCRYPTION_KEYS = ["dGhpcy1pcy1hLW5ldy1rZXktZm9yLXRlc3RzLTMyYnk=", old_key]
    assert mfa.decrypt_secret(token) == "JBSWY3DPEHPK3PXP"  # old key still decrypts


# --- Enrolment --------------------------------------------------------------------


@pytest.fixture
def owner():
    business = create_business()
    return business.user, business.organization


def _enrol(client):
    setup = client.post("/api/v1/auth/mfa/totp/setup/").json()
    code = pyotp.TOTP(setup["secret"]).now()
    response = client.post("/api/v1/auth/mfa/totp/confirm/", {"code": code})
    return setup, response


def test_enrolment_returns_qr_and_recovery_codes_and_secures_the_account(
    owner, mailoutbox, django_capture_on_commit_callbacks
):
    user, organization = owner
    client = client_for(user, organization, mfa=False)
    other_device = client_for(user, organization, mfa=False)

    with django_capture_on_commit_callbacks(execute=True):
        setup, response = _enrol(client)

    assert setup["qr_code"].startswith("data:image/png;base64,")
    assert setup["otpauth_uri"].startswith("otpauth://totp/ShopFlow:")
    assert response.status_code == 200
    assert len(response.json()["recovery_codes"]) == 10
    assert RecoveryCode.objects.filter(user=user).count() == 10
    assert setup["secret"] not in TOTPDevice.objects.get(user=user).secret_encrypted
    me = client.get("/api/v1/auth/me/").json()
    assert me["mfa_verified"] is True
    assert me["user"]["mfa_enabled"] is True
    # Any session opened before enrolment (maybe with a stolen password) is ended.
    assert other_device.get("/api/v1/auth/me/").status_code == 401
    assert [m.subject for m in mailoutbox] == [
        "ShopFlow security notice: Two-step verification was turned on"
    ]


def test_wrong_confirmation_code_is_rejected(owner):
    client = client_for(*owner, mfa=False)
    client.post("/api/v1/auth/mfa/totp/setup/")

    response = client.post("/api/v1/auth/mfa/totp/confirm/", {"code": "000000"})

    assert response.status_code == 400
    assert response.json()["code"] == "MFA_CODE_INVALID"
    assert TOTPDevice.objects.get().confirmed_at is None


def test_setup_cannot_silently_replace_an_active_authenticator(owner):
    client = client_for(*owner, mfa=False)
    _enrol(client)

    response = client.post("/api/v1/auth/mfa/totp/setup/")

    assert response.status_code == 409
    assert response.json()["code"] == "MFA_ALREADY_ENABLED"


# --- Signing in with two steps -----------------------------------------------------------


@pytest.fixture
def mfa_owner(owner):
    user, organization = owner
    setup, _ = _enrol(client_for(user, organization, mfa=False))
    return user, setup["secret"]


def _challenge(email):
    response = APIClient().post(LOGIN, {"email": email, "password": PASSWORD, "client": "mobile"})
    assert response.status_code == 401, response.content
    assert response.json()["code"] == "MFA_REQUIRED"
    return response.json()["mfa_token"]


def test_password_alone_does_not_open_a_session(mfa_owner):
    user, _ = mfa_owner
    sessions_before = AuthSession.objects.filter(user=user).count()

    _challenge(user.email)

    assert AuthSession.objects.filter(user=user).count() == sessions_before


def test_code_completes_sign_in_with_a_verified_session(mfa_owner):
    user, secret = mfa_owner
    with time_machine.travel(timezone.now() + timedelta(seconds=60), tick=False):
        token = _challenge(user.email)
        response = APIClient().post(
            VERIFY, {"mfa_token": token, "code": pyotp.TOTP(secret).now(), "client": "mobile"}
        )

    assert response.status_code == 200
    session = AuthSession.objects.get(pk=response.json()["session"]["id"])
    assert session.mfa_verified


def test_a_code_cannot_be_replayed_for_a_second_sign_in(mfa_owner):
    user, secret = mfa_owner
    with time_machine.travel(timezone.now() + timedelta(seconds=60), tick=False):
        code = pyotp.TOTP(secret).now()
        first = APIClient().post(
            VERIFY, {"mfa_token": _challenge(user.email), "code": code, "client": "mobile"}
        )
        replay = APIClient().post(
            VERIFY, {"mfa_token": _challenge(user.email), "code": code, "client": "mobile"}
        )

    assert first.status_code == 200
    assert replay.status_code == 400
    assert replay.json()["code"] == "MFA_CODE_INVALID"


def test_recovery_codes_work_once(owner):
    user, organization = owner
    _, response = _enrol(client_for(user, organization, mfa=False))
    recovery = response.json()["recovery_codes"][0]

    first = APIClient().post(
        VERIFY, {"mfa_token": _challenge(user.email), "code": recovery, "client": "mobile"}
    )
    again = APIClient().post(
        VERIFY, {"mfa_token": _challenge(user.email), "code": recovery, "client": "mobile"}
    )

    assert first.status_code == 200
    assert again.status_code == 400


def test_challenge_dies_after_five_wrong_codes(mfa_owner):
    user, secret = mfa_owner
    token = _challenge(user.email)
    for _ in range(settings.AUTH_MFA_MAX_ATTEMPTS):
        assert (
            APIClient()
            .post(VERIFY, {"mfa_token": token, "code": "000000", "client": "mobile"})
            .status_code
            == 400
        )

    with time_machine.travel(timezone.now() + timedelta(seconds=60), tick=False):
        response = APIClient().post(
            VERIFY, {"mfa_token": token, "code": pyotp.TOTP(secret).now(), "client": "mobile"}
        )

    assert response.json()["code"] == "TOKEN_INVALID"


def test_challenge_expires_after_five_minutes(mfa_owner):
    user, secret = mfa_owner
    token = _challenge(user.email)

    with time_machine.travel(timezone.now() + timedelta(minutes=5, seconds=1), tick=False):
        response = APIClient().post(
            VERIFY, {"mfa_token": token, "code": pyotp.TOTP(secret).now(), "client": "mobile"}
        )

    assert response.json()["code"] == "TOKEN_INVALID"


def test_web_second_step_requires_csrf(mfa_owner):
    user, secret = mfa_owner
    token = _challenge(user.email)

    response = APIClient(enforce_csrf_checks=True).post(
        VERIFY, {"mfa_token": token, "code": pyotp.TOTP(secret).now()}
    )

    assert response.status_code == 403


# --- Turning it off -------------------------------------------------------------------


def test_disabling_needs_password_and_code(mfa_owner):
    user, secret = mfa_owner
    client = client_for(user, None)

    wrong_password = client.post(
        "/api/v1/auth/mfa/totp/disable/", {"password": "nope", "code": "000000"}
    )
    wrong_code = client.post(
        "/api/v1/auth/mfa/totp/disable/", {"password": PASSWORD, "code": "000000"}
    )
    with time_machine.travel(timezone.now() + timedelta(seconds=60), tick=False):
        ok = client.post(
            "/api/v1/auth/mfa/totp/disable/",
            {"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        )

    assert wrong_password.status_code == 400
    assert wrong_code.status_code == 400
    assert ok.status_code == 204
    assert not TOTPDevice.objects.filter(user=user).exists()
    signed_in = APIClient().post(
        LOGIN, {"email": user.email, "password": PASSWORD, "client": "mobile"}
    )
    assert signed_in.status_code == 200


# --- Enforcement for sensitive permissions ------------------------------------------------


def test_sensitive_actions_need_two_step_verification(owner, settings):
    user, organization = owner
    client = client_for(user, organization, mfa=False)

    everyday = client.get("/api/v1/stores/")
    sensitive = client.post("/api/v1/stores/", {"code": "S2", "name": "Branch"})

    assert everyday.status_code == 200
    assert sensitive.status_code == 403
    body = sensitive.json()
    assert body["code"] == "MFA_ENROLLMENT_REQUIRED"
    assert body["errors"][0]["meta"] == {"permission": "stores.manage"}

    _enrol(client)  # enrolling verifies this very session
    assert client.post("/api/v1/stores/", {"code": "S2", "name": "Branch"}).status_code == 201


def test_enforcement_can_be_switched_off(owner, settings):
    settings.MFA_ENFORCEMENT = False
    client = client_for(*owner, mfa=False)

    assert client.post("/api/v1/stores/", {"code": "S2", "name": "Branch"}).status_code == 201
