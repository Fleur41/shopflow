"""Test runs (pytest, CI). Uses a real PostgreSQL; never SQLite."""

import os

os.environ.setdefault(
    "JWT_SIGNING_KEYS",
    "test=test-only-jwt-signing-key-0123456789abcdef,old=test-only-previous-jwt-key-0123456789abcd",
)
os.environ.setdefault("JWT_ACTIVE_KEY_ID", "test")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DATABASE_URL", "postgres://shopflow:shopflow@localhost:5432/shopflow")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from .base import *

ALLOWED_HOSTS = ["testserver", "localhost"]

# Fast hashing in tests only; production uses Argon2id (see base.py).
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
