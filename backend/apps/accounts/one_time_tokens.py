"""Single-use tokens for emailed links and the second sign-in step."""

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.common.errors import ApplicationError

from .models import OneTimeToken, User
from .tokens import generate_refresh_token, hash_refresh_token


class TokenInvalid(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "TOKEN_INVALID"
    title = "Link invalid or expired"


def issue(
    user: User, purpose: str, lifetime: timedelta, payload: dict[str, Any] | None = None
) -> str:
    """Create a token (returning the raw value once) and retire older ones."""
    raw = generate_refresh_token()
    now = timezone.now()
    with transaction.atomic():
        OneTimeToken.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(
            used_at=now
        )
        OneTimeToken.objects.create(
            user=user,
            purpose=purpose,
            token_hash=hash_refresh_token(raw),
            expires_at=now + lifetime,
            payload=payload or {},
        )
    return raw


def lock_open(raw: str, purpose: str) -> OneTimeToken:
    """Lock an unused, unexpired token (call inside a transaction) or raise TokenInvalid."""
    token = (
        OneTimeToken.objects.select_for_update()
        .select_related("user")
        .filter(token_hash=hash_refresh_token(raw), purpose=purpose)
        .first()
    )
    if (
        token is None
        or token.used_at is not None
        or token.expires_at <= timezone.now()
        or not token.user.is_active
    ):
        raise TokenInvalid("This link is invalid or has expired. Request a new one.")
    return token


def mark_used(token: OneTimeToken) -> None:
    token.used_at = timezone.now()
    token.save(update_fields=["used_at", "updated_at"])
