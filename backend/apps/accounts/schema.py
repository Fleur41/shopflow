"""OpenAPI descriptions of the authentication schemes (drf-spectacular)."""

from typing import Any

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema


class BearerTokenScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.BearerTokenAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema: AutoSchema) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Mobile clients: access token from /auth/login/ or /auth/refresh/.",
        }


class CookieTokenScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.CookieTokenAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema: AutoSchema) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.AUTH_ACCESS_COOKIE_NAME,
            "description": "Web clients: HttpOnly cookie set at sign-in. Unsafe methods "
            "also need the X-CSRFToken header.",
        }
