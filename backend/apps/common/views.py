"""Plain Django views: health probes and JSON error handlers.

Error handlers make non-DRF failures (unknown URLs, crashes outside DRF views)
return the same problem-details JSON as the API instead of HTML pages.
"""

import structlog
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase
from django.views import static
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_safe

from .errors import PROBLEM_CONTENT_TYPE, problem, request_id_of

logger = structlog.get_logger(__name__)


@never_cache
@require_GET
def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness: the process is up. Checks no dependencies."""
    return JsonResponse({"status": "ok"})


@never_cache
@require_GET
def readyz(request: HttpRequest) -> JsonResponse:
    """Readiness: the database and cache answer and all migrations are applied."""
    checks = {
        "database": _check_database(),
        "migrations": _check_migrations(),
        "cache": _check_cache(),
    }
    ready = all(result == "ok" for result in checks.values())
    return JsonResponse(
        {"status": "ok" if ready else "unavailable", "checks": checks},
        status=200 if ready else 503,
    )


def _check_database() -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("readyz.database_failed")
        return "error"
    return "ok"


def _check_migrations() -> str:
    try:
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception:
        logger.exception("readyz.migrations_check_failed")
        return "error"
    return "pending" if plan else "ok"


def _check_cache() -> str:
    try:
        cache.set("readyz", "1", timeout=5)
        ok = cache.get("readyz") == "1"
    except Exception:
        logger.exception("readyz.cache_failed")
        return "error"
    return "ok" if ok else "error"


def _problem_response(
    request: HttpRequest, status_code: int, code: str, title: str, detail: str
) -> JsonResponse:
    body = problem(
        status_code=status_code,
        code=code,
        title=title,
        detail=detail,
        request_id=request_id_of(request),
    )
    return JsonResponse(body, status=status_code, content_type=PROBLEM_CONTENT_TYPE)


def bad_request(request: HttpRequest, exception: Exception) -> JsonResponse:
    return _problem_response(
        request, 400, "MALFORMED_REQUEST", "Malformed request", "The request was invalid."
    )


def permission_denied(request: HttpRequest, exception: Exception) -> JsonResponse:
    return _problem_response(
        request,
        403,
        "PERMISSION_DENIED",
        "Permission denied",
        "You do not have permission to perform this action.",
    )


def not_found(request: HttpRequest, exception: Exception) -> JsonResponse:
    return _problem_response(
        request, 404, "NOT_FOUND", "Not found", "The requested resource was not found."
    )


def server_error(request: HttpRequest) -> JsonResponse:
    return _problem_response(
        request,
        500,
        "INTERNAL_ERROR",
        "Something went wrong",
        "An unexpected error occurred. Quote the request ID if you contact support.",
    )


def csrf_failure(request: HttpRequest, reason: str = "") -> JsonResponse:
    """``CSRF_FAILURE_VIEW``: CSRF rejections use the same JSON shape as the API."""
    return _problem_response(
        request,
        403,
        "CSRF_FAILED",
        "Security check failed",
        "Your session's security token is missing or invalid. Refresh the page and try again.",
    )


@require_safe
def serve_media(request: HttpRequest, path: str) -> HttpResponseBase:
    """Uploaded files, in local development only (deployments use object storage).

    Served as inert content: displayed inline, never sniffed as another type,
    and sandboxed so even a crafted file can't run script on this origin.
    """
    response = static.serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Cross-Origin-Resource-Policy"] = "cross-origin"
    return response
