"""Local development. Never used with real data or real credentials."""

import os

os.environ.setdefault("JWT_SIGNING_KEYS", "dev=dev-only-insecure-jwt-signing-key-0123456789")
os.environ.setdefault("JWT_ACTIVE_KEY_ID", "dev")
os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-do-not-use-elsewhere")
os.environ.setdefault("LOG_JSON", "false")

from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "backend"]  # noqa: S104

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
# The Next.js dev server proxies /api/* with Host "backend:8000", while
# browsers send Origin "http://localhost:3000"; trust that origin for CSRF.
# (In deployments the reverse proxy preserves Host, so origins match.)
CSRF_TRUSTED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# Local development runs over plain HTTP, where browsers reject Secure and
# prefixed cookies.
AUTH_COOKIE_SECURE = False
AUTH_ACCESS_COOKIE_NAME = "sf_at"
AUTH_REFRESH_COOKIE_NAME = "sf_rt"

# Repeated local end-to-end runs register many businesses.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
    "signup": "200/hour",
}

SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.AllowAny"]
