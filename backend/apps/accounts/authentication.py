"""DRF authentication: Bearer tokens (mobile) and HttpOnly cookies (web).

Both verify the access token, then check that its session is still active, so
sign-out and revocation take effect on the next request. Cookie-authenticated
requests must also pass CSRF validation, because browsers attach cookies to
cross-site requests automatically; Bearer headers are never sent implicitly.
"""

from django.conf import settings
from django.http import HttpRequest
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, CSRFCheck
from rest_framework.request import Request

from .models import User
from .services import get_session_state
from .tokens import AccessClaims, ExpiredAccessToken, InvalidAccessToken, decode_access_token

_INVALID = "Authentication credentials are invalid."


class TokenExpired(exceptions.AuthenticationFailed):
    default_detail = "Your access token has expired. Refresh it and try again."
    default_code = "token_expired"


class SessionRevoked(exceptions.AuthenticationFailed):
    default_detail = "This session has ended. Please sign in again."
    default_code = "session_revoked"


class CsrfFailed(exceptions.PermissionDenied):
    default_detail = (
        "Your session's security token is missing or invalid. Refresh the page and try again."
    )
    default_code = "csrf_failed"


def authenticate_access_token(raw_token: str) -> tuple[User, AccessClaims]:
    try:
        claims = decode_access_token(raw_token)
    except ExpiredAccessToken as exc:
        raise TokenExpired from exc
    except InvalidAccessToken as exc:
        raise exceptions.AuthenticationFailed(_INVALID) from exc

    state = get_session_state(claims.session_id)
    if state is None or not state.active or state.user_id != claims.user_id:
        raise SessionRevoked

    user = User.objects.filter(pk=claims.user_id, is_active=True).first()
    if user is None:
        raise SessionRevoked
    return user, claims


def enforce_csrf(request: Request | HttpRequest) -> None:
    """Apply Django's CSRF check (token + Origin/Referer) to a DRF request."""
    django_request = request._request if isinstance(request, Request) else request

    def _noop(_request: HttpRequest) -> None:
        return None

    check = CSRFCheck(_noop)  # type: ignore[arg-type]
    check.process_request(django_request)
    reason = check.process_view(django_request, None, (), {})  # type: ignore[arg-type]
    if reason:
        raise CsrfFailed


class BearerTokenAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request: Request) -> tuple[User, AccessClaims] | None:
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        scheme, _, token = header.partition(" ")
        if scheme.lower() != self.keyword.lower():
            return None
        token = token.strip()
        if not token or " " in token:
            raise exceptions.AuthenticationFailed(_INVALID)
        return authenticate_access_token(token)

    def authenticate_header(self, request: Request) -> str:
        return f'{self.keyword} realm="api"'


class CookieTokenAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[User, AccessClaims] | None:
        token = request.COOKIES.get(settings.AUTH_ACCESS_COOKIE_NAME)
        if not token:
            return None
        result = authenticate_access_token(token)
        if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
            enforce_csrf(request)
        return result
