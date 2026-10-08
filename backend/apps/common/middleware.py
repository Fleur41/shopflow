import re
import time
import uuid
from collections.abc import Callable

import structlog
from django.http import HttpRequest, HttpResponse

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller-supplied request ID only if it is short and harmless to log.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UNLOGGED_PATHS = frozenset({"/healthz", "/readyz"})


class RequestIDMiddleware:
    """Assign every request an ID, bind it to all log lines, and log completion.

    The ID is returned in the ``X-Request-ID`` response header and in error
    bodies so users can quote it to support. Only the path is logged, never
    the query string, which may contain search terms such as phone numbers.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            if request.path not in _UNLOGGED_PATHS:
                logger.info(
                    "request.finished",
                    method=request.method,
                    path=request.path,
                    status=response.status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
            return response
        finally:
            structlog.contextvars.clear_contextvars()
