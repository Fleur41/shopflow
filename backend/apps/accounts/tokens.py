"""Access and refresh tokens (docs/SECURITY.md §2.2).

* Access tokens are short-lived JWTs (HS256) carrying only identity: user,
  session and expiry. Permissions are never embedded; they are resolved per
  request so changes apply immediately.
* Refresh tokens are 256-bit random strings. Only their SHA-256 hash is
  stored, so a database leak does not yield usable tokens.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

ALGORITHM = "HS256"
MIN_SIGNING_KEY_LENGTH = 32
_LEEWAY_SECONDS = 10


class InvalidAccessToken(Exception):
    """The token is malformed, tampered with, or not one of ours."""


class ExpiredAccessToken(InvalidAccessToken):
    """The token was valid but has expired; the client should refresh."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    token_id: str
    expires_at: datetime


def signing_keys() -> tuple[str, dict[str, str]]:
    """Return ``(active_kid, {kid: secret})``, validating the configuration."""
    keys: dict[str, str] = settings.JWT_SIGNING_KEYS
    active: str = settings.JWT_ACTIVE_KEY_ID
    if active not in keys:
        raise ImproperlyConfigured("JWT_ACTIVE_KEY_ID must name a key in JWT_SIGNING_KEYS.")
    weak = [kid for kid, secret in keys.items() if len(secret) < MIN_SIGNING_KEY_LENGTH]
    if weak:
        raise ImproperlyConfigured(
            f"JWT signing keys must be at least {MIN_SIGNING_KEY_LENGTH} characters: {weak}"
        )
    return active, keys


def issue_access_token(*, user_id: uuid.UUID, session_id: uuid.UUID) -> tuple[str, datetime]:
    """Return a signed access token and its expiry time."""
    active_kid, keys = signing_keys()
    now = timezone.now()
    expires_at = now + settings.AUTH_ACCESS_TOKEN_LIFETIME
    payload = {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": secrets.token_hex(16),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, keys[active_kid], algorithm=ALGORITHM, headers={"kid": active_kid})
    return token, expires_at


def decode_access_token(token: str) -> AccessClaims:
    """Verify signature, issuer, audience, type and expiry; return the claims."""
    _, keys = signing_keys()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in keys:
            raise InvalidAccessToken("Unknown signing key.")
        payload = jwt.decode(
            token,
            keys[kid],
            algorithms=[ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            leeway=_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "sid", "jti", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredAccessToken("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidAccessToken("Access token is invalid.") from exc

    if payload["typ"] != "access":
        raise InvalidAccessToken("Not an access token.")
    try:
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            token_id=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (ValueError, TypeError) as exc:
        raise InvalidAccessToken("Malformed claims.") from exc


def generate_refresh_token() -> str:
    """Return a new random refresh token (shown to the client exactly once)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest. Tokens are high-entropy, so no salt is needed."""
    return hashlib.sha256(token.encode()).hexdigest()
