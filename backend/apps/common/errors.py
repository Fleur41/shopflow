"""Standardized API errors (RFC 9457 problem details).

Every error response has the shape documented in docs/API.md §2:

    {"type", "title", "status", "code", "detail", "errors"?, "request_id"}

``code`` is stable and machine-readable; ``detail`` is safe to show to users.
Domain services raise :class:`ApplicationError` (or a subclass) for business
rule violations; DRF and Django exceptions are translated here.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import OperationalError
from django.http import Http404, HttpRequest
from rest_framework import exceptions, status
from rest_framework.response import Response

PROBLEM_CONTENT_TYPE = "application/problem+json"
_TYPE_PREFIX = "urn:shopflow:error:"


class ApplicationError(Exception):
    """A business rule rejected the request.

    Subclass per domain error, e.g. ``InsufficientStock(ApplicationError)``
    with ``code = "INSUFFICIENT_STOCK"``.
    """

    status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY
    code: str = "BUSINESS_RULE_VIOLATION"
    title: str = "The request could not be completed"

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        title: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if title is not None:
            self.title = title
        self.errors = errors or []
        self.headers = headers or {}


# DRF exception class → (code, title). Looked up along the MRO, most specific first.
_DRF_ERRORS: dict[type[exceptions.APIException], tuple[str, str]] = {
    exceptions.ValidationError: ("VALIDATION_ERROR", "Invalid request"),
    exceptions.ParseError: ("MALFORMED_REQUEST", "Malformed request"),
    exceptions.AuthenticationFailed: ("NOT_AUTHENTICATED", "Authentication failed"),
    exceptions.NotAuthenticated: ("NOT_AUTHENTICATED", "Authentication required"),
    exceptions.PermissionDenied: ("PERMISSION_DENIED", "Permission denied"),
    exceptions.NotFound: ("NOT_FOUND", "Not found"),
    exceptions.MethodNotAllowed: ("METHOD_NOT_ALLOWED", "Method not allowed"),
    exceptions.NotAcceptable: ("NOT_ACCEPTABLE", "Not acceptable"),
    exceptions.UnsupportedMediaType: ("UNSUPPORTED_MEDIA_TYPE", "Unsupported media type"),
    exceptions.Throttled: ("RATE_LIMITED", "Too many requests"),
}


def problem(
    *,
    status_code: int,
    code: str,
    title: str,
    detail: str,
    request_id: str | None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a problem-details body."""
    body: dict[str, Any] = {
        "type": _TYPE_PREFIX + code.lower().replace("_", "-"),
        "title": title,
        "status": status_code,
        "code": code,
        "detail": detail,
    }
    if errors:
        body["errors"] = errors
    body["request_id"] = request_id
    return body


def exception_handler(exc: Exception, context: Mapping[str, Any]) -> Response | None:
    """DRF ``EXCEPTION_HANDLER``.

    Returns ``None`` for unexpected exceptions so they propagate to Django,
    which logs them (and reports them to Sentry) and renders the JSON 500
    handler in :mod:`apps.common.views`.
    """
    if isinstance(exc, OperationalError) and is_lock_timeout(exc):
        exc = ApplicationError(
            "Someone else is updating the same records right now. Please try again.",
            code="LOCK_TIMEOUT",
            title="Busy, please retry",
            status_code=status.HTTP_409_CONFLICT,
            headers={"Retry-After": "1"},
        )

    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    request = context.get("request")
    request_id = getattr(request, "request_id", None)

    if isinstance(exc, ApplicationError):
        body = problem(
            status_code=exc.status_code,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            request_id=request_id,
            errors=exc.errors,
        )
        return Response(
            body, status=exc.status_code, headers=exc.headers, content_type=PROBLEM_CONTENT_TYPE
        )

    if not isinstance(exc, exceptions.APIException):
        return None

    code, title = _lookup_drf_error(exc)
    errors: list[dict[str, Any]] = []
    if isinstance(exc, exceptions.ValidationError):
        errors = flatten_validation_errors(exc.detail)
        detail = "One or more fields are invalid."
    else:
        detail = str(exc.detail)

    headers: dict[str, str] = {}
    auth_header = getattr(exc, "auth_header", None)
    if auth_header:
        headers["WWW-Authenticate"] = auth_header
    wait = getattr(exc, "wait", None)
    if wait is not None:
        headers["Retry-After"] = str(int(wait))

    body = problem(
        status_code=exc.status_code,
        code=code,
        title=title,
        detail=detail,
        request_id=request_id,
        errors=errors,
    )
    return Response(
        body, status=exc.status_code, headers=headers, content_type=PROBLEM_CONTENT_TYPE
    )


def _lookup_drf_error(exc: exceptions.APIException) -> tuple[str, str]:
    code, title = str(exc.default_code).upper(), "Request failed"
    generic_code = exc.default_code
    # The mapped classes are all direct APIException subclasses, so at most one matches.
    for cls, (mapped_code, mapped_title) in _DRF_ERRORS.items():
        if isinstance(exc, cls):
            code, title, generic_code = mapped_code, mapped_title, cls.default_code
            break
    # A specific code (a subclass such as TokenExpired, or code="..." passed
    # when raising) is more useful to clients than the generic one.
    specific = getattr(exc.detail, "code", None)
    if isinstance(specific, str) and specific != generic_code:
        code = specific.upper()
    return code, title


def flatten_validation_errors(detail: Any, pointer: str = "") -> list[dict[str, Any]]:
    """Turn DRF's nested error structure into a flat list with JSON pointers.

    ``{"items": [{"quantity": ["Must be positive."]}]}`` becomes
    ``[{"pointer": "/items/0/quantity", "code": "invalid", "detail": "..."}]``.
    Errors that are not tied to a field (``non_field_errors``) point at the
    document root (``""``).
    """
    if isinstance(detail, Mapping):
        flat: list[dict[str, Any]] = []
        for key, value in detail.items():
            child = pointer if key == "non_field_errors" else f"{pointer}/{_escape(str(key))}"
            flat.extend(flatten_validation_errors(value, child))
        return flat
    if isinstance(detail, Sequence) and not isinstance(detail, str):
        flat = []
        for index, value in enumerate(detail):
            if isinstance(value, Mapping | list):
                flat.extend(flatten_validation_errors(value, f"{pointer}/{index}"))
            else:
                flat.extend(flatten_validation_errors(value, pointer))
        return flat
    return [
        {
            "pointer": pointer,
            "code": str(getattr(detail, "code", "invalid")).upper(),
            "detail": str(detail),
        }
    ]


def _escape(token: str) -> str:
    # RFC 6901: "~" → "~0", "/" → "~1"
    return token.replace("~", "~0").replace("/", "~1")


_LOCK_NOT_AVAILABLE = "55P03"  # PostgreSQL: lock_timeout expired


def is_lock_timeout(exc: BaseException) -> bool:
    """True if a database error was caused by ``lock_timeout`` expiring."""
    cause = exc.__cause__ or exc.__context__
    return getattr(cause, "sqlstate", None) == _LOCK_NOT_AVAILABLE


def request_id_of(request: HttpRequest) -> str | None:
    return getattr(request, "request_id", None)
