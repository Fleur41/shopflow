from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from ..models import normalize_email_address
from ..services import email_fingerprint


class LoginIPThrottle(SimpleRateThrottle):
    """Caps sign-in attempts per client IP (credential stuffing across accounts)."""

    scope = "login_ip"

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginEmailThrottle(SimpleRateThrottle):
    """Caps sign-in attempts per email address (password guessing on one account)."""

    scope = "login_email"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        email = request.data.get("email") if hasattr(request.data, "get") else None
        if not isinstance(email, str) or not email.strip():
            return None
        ident = email_fingerprint(normalize_email_address(email))
        return self.cache_format % {"scope": self.scope, "ident": ident}


class RefreshThrottle(SimpleRateThrottle):
    scope = "auth_refresh"

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
