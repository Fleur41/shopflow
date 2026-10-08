import uuid
from datetime import timedelta

import jwt
import pytest
import time_machine
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.accounts.tokens import (
    ExpiredAccessToken,
    InvalidAccessToken,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
    issue_access_token,
    signing_keys,
)

USER_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()


def test_access_token_round_trip():
    token, expires_at = issue_access_token(user_id=USER_ID, session_id=SESSION_ID)

    claims = decode_access_token(token)

    assert claims.user_id == USER_ID
    assert claims.session_id == SESSION_ID
    assert claims.expires_at == expires_at.replace(microsecond=0)
    assert jwt.get_unverified_header(token)["kid"] == "test"


def test_access_token_carries_no_permissions_or_personal_data():
    token, _ = issue_access_token(user_id=USER_ID, session_id=SESSION_ID)

    payload = jwt.decode(token, options={"verify_signature": False})

    assert set(payload) == {"iss", "aud", "sub", "sid", "jti", "typ", "iat", "exp"}


def test_access_token_expires_after_ten_minutes():
    with time_machine.travel(timezone.now(), tick=False) as traveller:
        token, _ = issue_access_token(user_id=USER_ID, session_id=SESSION_ID)
        traveller.shift(timedelta(minutes=9, seconds=59))
        decode_access_token(token)
        traveller.shift(timedelta(minutes=1))
        with pytest.raises(ExpiredAccessToken):
            decode_access_token(token)


def test_tampered_token_is_rejected():
    token, _ = issue_access_token(user_id=USER_ID, session_id=SESSION_ID)
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload}.{signature[:-2]}AA"

    with pytest.raises(InvalidAccessToken):
        decode_access_token(forged)


def test_token_signed_with_unknown_key_is_rejected():
    token = jwt.encode(
        {"sub": str(USER_ID)}, "x" * 40, algorithm="HS256", headers={"kid": "attacker"}
    )

    with pytest.raises(InvalidAccessToken):
        decode_access_token(token)


def test_unsigned_alg_none_token_is_rejected():
    token = jwt.encode({"sub": str(USER_ID)}, key="", algorithm="none", headers={"kid": "test"})

    with pytest.raises(InvalidAccessToken):
        decode_access_token(token)


@pytest.mark.parametrize(
    ("claim", "value"), [("aud", "another-api"), ("iss", "someone-else"), ("typ", "refresh")]
)
def test_tokens_for_other_audiences_issuers_or_types_are_rejected(settings, claim, value):
    now = int(timezone.now().timestamp())
    payload = {
        "iss": "shopflow",
        "aud": "shopflow-api",
        "sub": str(USER_ID),
        "sid": str(SESSION_ID),
        "jti": "j",
        "typ": "access",
        "iat": now,
        "exp": now + 60,
    }
    payload[claim] = value
    token = jwt.encode(
        payload, settings.JWT_SIGNING_KEYS["test"], algorithm="HS256", headers={"kid": "test"}
    )

    with pytest.raises(InvalidAccessToken):
        decode_access_token(token)


def test_tokens_signed_with_previous_key_still_verify_during_rotation(settings):
    settings.JWT_ACTIVE_KEY_ID = "old"
    token, _ = issue_access_token(user_id=USER_ID, session_id=SESSION_ID)
    settings.JWT_ACTIVE_KEY_ID = "test"

    assert decode_access_token(token).user_id == USER_ID


def test_active_key_must_exist(settings):
    settings.JWT_ACTIVE_KEY_ID = "missing"

    with pytest.raises(ImproperlyConfigured):
        signing_keys()


def test_short_signing_keys_are_refused(settings):
    settings.JWT_SIGNING_KEYS = {"test": "too-short"}

    with pytest.raises(ImproperlyConfigured, match="at least 32"):
        signing_keys()


def test_refresh_tokens_are_random_and_hashed_deterministically():
    first, second = generate_refresh_token(), generate_refresh_token()

    assert first != second
    assert len(first) >= 43  # 256 bits, base64url
    assert hash_refresh_token(first) == hash_refresh_token(first)
    assert len(hash_refresh_token(first)) == 64
    assert first not in hash_refresh_token(first)
