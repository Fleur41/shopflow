"""Web clients hold tokens only in HttpOnly cookies (docs/SECURITY.md §2.2)."""

import math
from datetime import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework.response import Response

from ..services import IssuedTokens


def _seconds_until(moment: datetime) -> int:
    return max(0, math.ceil((moment - timezone.now()).total_seconds()))


def set_auth_cookies(response: Response, issued: IssuedTokens) -> None:
    response.set_cookie(
        settings.AUTH_ACCESS_COOKIE_NAME,
        issued.access_token,
        max_age=_seconds_until(issued.access_expires_at),
        path="/",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        issued.refresh_token,
        max_age=_seconds_until(issued.refresh_expires_at),
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="Strict",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.AUTH_ACCESS_COOKIE_NAME, path="/", samesite="Lax")
    response.delete_cookie(
        settings.AUTH_REFRESH_COOKIE_NAME,
        path=settings.AUTH_REFRESH_COOKIE_PATH,
        samesite="Strict",
    )
