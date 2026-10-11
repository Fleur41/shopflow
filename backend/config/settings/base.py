"""Settings shared by every environment.

Environment-specific modules (dev, test, prod) import from here and override.
All secrets and deployment-specific values come from environment variables;
see the repository's .env.example for the full list.
"""

from datetime import timedelta
from pathlib import Path

import environ

from apps.common.logging import build_logging_config

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS: list[str] = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "apps.common",
    "apps.accounts",
    "apps.organizations",
    "apps.catalog",
    "apps.payments",
    "apps.audit",
    "apps.idempotency",
]

MIDDLEWARE = [
    "apps.common.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# CSRF rejections return problem JSON instead of an HTML page.
CSRF_FAILURE_VIEW = "apps.common.views.csrf_failure"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -------------------------------------------------------------
# Business operations open their own transactions in the service layer, so
# ATOMIC_REQUESTS stays off (see docs/ARCHITECTURE.md, request lifecycle).
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
# The runtime role the app connects as in deployed environments. After every
# migrate (run as the schema owner) it is granted row access only, with no
# UPDATE/DELETE on append-only tables. Empty disables grant management.
DATABASE_APP_ROLE: str = env("DATABASE_APP_ROLE", default="")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Cache ----------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "KEY_PREFIX": "shopflow",
    }
}

# --- Authentication -------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Token-based API authentication (docs/SECURITY.md §2).
# JWT_SIGNING_KEYS maps key IDs to secrets ("kid1=secret1,kid2=secret2"). New
# tokens are signed with JWT_ACTIVE_KEY_ID; the other keys still verify tokens
# during a key rotation. Each secret must be at least 32 characters.
JWT_SIGNING_KEYS: dict[str, str] = env.dict("JWT_SIGNING_KEYS")
JWT_ACTIVE_KEY_ID: str = env("JWT_ACTIVE_KEY_ID")
JWT_ISSUER = "shopflow"
JWT_AUDIENCE = "shopflow-api"

AUTH_ACCESS_TOKEN_LIFETIME = timedelta(minutes=10)
AUTH_WEB_REFRESH_IDLE_LIFETIME = timedelta(days=14)
AUTH_WEB_SESSION_MAX_LIFETIME = timedelta(days=30)
AUTH_MOBILE_REFRESH_IDLE_LIFETIME = timedelta(days=30)
AUTH_MOBILE_SESSION_MAX_LIFETIME = timedelta(days=90)
# A rotated refresh token presented again within this window is treated as a
# benign race (e.g. two browser tabs refreshing at once), not as theft.
AUTH_REFRESH_REUSE_GRACE = timedelta(seconds=20)
# How long a session's validity is cached. Revocation clears the cache entry
# immediately, so this only bounds staleness if the cache delete is lost.
AUTH_SESSION_CACHE_SECONDS = 30

AUTH_LOCKOUT_THRESHOLD = 10
AUTH_LOCKOUT_WINDOW = timedelta(minutes=15)
AUTH_LOCKOUT_DURATION = timedelta(minutes=15)

# Web clients receive tokens only as HttpOnly cookies. The __Host-/__Secure-
# prefixes make browsers enforce Secure and (for __Host-) the exact host.
AUTH_COOKIE_SECURE = True
AUTH_ACCESS_COOKIE_NAME = "__Host-sf_at"
AUTH_REFRESH_COOKIE_NAME = "__Secure-sf_rt"
AUTH_REFRESH_COOKIE_PATH = "/api/v1/auth/"

# Idempotency keys (docs/API.md §3): kept longer than any plausible offline
# window. A duplicate request waits at most IDEMPOTENCY_LOCK_TIMEOUT for the
# first copy to finish before getting 409 IDEMPOTENCY_IN_PROGRESS.
IDEMPOTENCY_KEY_TTL = timedelta(days=30)
IDEMPOTENCY_LOCK_TIMEOUT = timedelta(seconds=5)

# --- Account lifecycle (Phase 1.9) ------------------------------------------
# Links in emails point at the web app.
FRONTEND_URL: str = env("FRONTEND_URL", default="http://localhost:3000").rstrip("/")
EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL: str = env("DEFAULT_FROM_EMAIL", default="ShopFlow <no-reply@shopflow.local>")

AUTH_EMAIL_VERIFICATION_LIFETIME = timedelta(hours=24)
AUTH_PASSWORD_RESET_LIFETIME = timedelta(minutes=30)
AUTH_MFA_CHALLENGE_LIFETIME = timedelta(minutes=5)
AUTH_MFA_MAX_ATTEMPTS = 5
INVITATION_LIFETIME = timedelta(days=7)

# Two-step verification (TOTP). Secrets are encrypted at rest with Fernet;
# the first key encrypts, all keys decrypt (rotation). Holders of sensitive
# permissions must have verified MFA in their session to use them.
MFA_ENCRYPTION_KEYS: list[str] = env.list("MFA_ENCRYPTION_KEYS")
MFA_ENFORCEMENT: bool = env.bool("MFA_ENFORCEMENT", default=True)
MFA_ISSUER = "ShopFlow"

# --- Internationalisation -------------------------------------------------
# All timestamps are stored in UTC; business days use each store's timezone.
LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Uploaded files (product images) --------------------------------------
# Uploads are served from a different origin than the web app (docs/SECURITY.md
# §7): object storage or a CDN when deployed (8.2), Django's own port locally.
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
MEDIA_URL = env("MEDIA_URL", default="/media/")

# --- Admin ----------------------------------------------------------------
# Platform-staff admin only. Production must set a non-default path.
ADMIN_URL: str = env("DJANGO_ADMIN_URL", default="admin/")

# --- Django REST Framework ------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.BearerTokenAuthentication",
        "apps.accounts.authentication.CookieTokenAuthentication",
    ],
    # Deny by default: every endpoint must opt out explicitly to be public.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
        "user": "600/min",
        "login_ip": "20/min",
        "login_email": "5/min",
        "auth_refresh": "60/min",
        "signup": "10/hour",
        "password_reset_email": "3/hour",
        "password_reset_ip": "10/hour",
        "email_verification": "3/hour",
        "mfa_verify": "10/min",
        "invitation_token": "30/hour",
    },
    # Number of trusted reverse proxies in front of the API; used to read the
    # client IP from X-Forwarded-For for throttling and session records.
    "NUM_PROXIES": env.int("TRUSTED_PROXY_COUNT", default=0),
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultCursorPagination",
    "EXCEPTION_HANDLER": "apps.common.errors.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "COERCE_DECIMAL_TO_STRING": True,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ShopFlow API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    # Explicit names for enums whose field names are too generic to stay unique.
    "ENUM_NAME_OVERRIDES": {
        "PaymentMethodKind": "apps.payments.models.PaymentMethod.Kind",
        "EtimsPaymentType": "apps.payments.models.PaymentMethod.EtimsPaymentType",
        "PaymentProvider": "apps.payments.models.PROVIDER_CHOICES",
    },
}

# --- Logging --------------------------------------------------------------
LOGGING = build_logging_config(
    json_logs=env.bool("LOG_JSON", default=True),
    level=env("LOG_LEVEL", default="INFO"),
)
