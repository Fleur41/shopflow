"""Local development. Never used with real data or real credentials."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-do-not-use-elsewhere")
os.environ.setdefault("LOG_JSON", "false")

from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "backend"]  # noqa: S104

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.AllowAny"]
