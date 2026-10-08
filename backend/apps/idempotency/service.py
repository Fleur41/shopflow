"""Exactly-once execution for retried requests (docs/API.md §3).

    @idempotent(required=True)
    def post(self, request): ...

* First request: the key is inserted, the handler runs, and the response is
  stored, all in one transaction. If the handler fails, everything (key
  included) rolls back and the client may retry with the same key.
* Retry with the same key and the same request: the stored response is
  returned with ``Idempotent-Replayed: true``. Nothing runs twice.
* Same key, different request (or a different user): ``422
  IDEMPOTENCY_KEY_REUSED``.
* Two copies at once: the second waits on the unique index until the first
  commits, then replays it. If it waits too long: ``409
  IDEMPOTENCY_IN_PROGRESS``; retrying later is safe.
"""

import functools
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, TypeVar

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, OperationalError, connection, transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.errors import ApplicationError, is_lock_timeout
from apps.organizations.context import RequestContext, get_request_context

from .models import IdempotencyKey

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
_VALID_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,255}$")


class IdempotencyKeyRequired(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "IDEMPOTENCY_KEY_REQUIRED"
    title = "Idempotency-Key header required"


class IdempotencyKeyInvalid(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "IDEMPOTENCY_KEY_INVALID"
    title = "Invalid Idempotency-Key header"


class IdempotencyKeyReused(ApplicationError):
    code = "IDEMPOTENCY_KEY_REUSED"
    title = "Idempotency key already used"


class IdempotencyInProgress(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    code = "IDEMPOTENCY_IN_PROGRESS"
    title = "Request still being processed"


def request_fingerprint(request: Request) -> str:
    body = json.dumps(request.data, sort_keys=True, cls=DjangoJSONEncoder, separators=(",", ":"))
    return hashlib.sha256(f"{request.method} {request.path}\n{body}".encode()).hexdigest()


def run_idempotent(
    request: Request,
    ctx: RequestContext,
    endpoint: str,
    handler: Callable[[], Response],
    *,
    required: bool,
) -> Response:
    key = request.headers.get(HEADER, "").strip()
    if not key:
        if required:
            raise IdempotencyKeyRequired(
                f"Send a unique {HEADER} header (e.g. a UUID) so retries can't duplicate this."
            )
        return handler()
    if not _VALID_KEY.match(key):
        raise IdempotencyKeyInvalid(
            f"{HEADER} must be 8-255 characters: letters, digits and . _ : -"
        )

    fingerprint = request_fingerprint(request)
    with transaction.atomic():
        _bound_lock_wait()
        try:
            with transaction.atomic():  # savepoint: a duplicate key must not abort the outer one
                record = IdempotencyKey.objects.create(
                    organization=ctx.organization,
                    user=ctx.user,
                    key=key,
                    endpoint=endpoint,
                    request_hash=fingerprint,
                    expires_at=timezone.now() + settings.IDEMPOTENCY_KEY_TTL,
                )
        except IntegrityError:
            return _replay(ctx, key, endpoint, fingerprint)
        except OperationalError as exc:
            if not is_lock_timeout(exc):
                raise
            raise IdempotencyInProgress(
                "An identical request is still being processed. Retry shortly."
            ) from exc

        response = handler()
        if not status.is_success(response.status_code):
            # Only successes are remembered; anything else rolls back with the key.
            transaction.set_rollback(True)
            return response
        record.response_status = response.status_code
        record.response_body = response.data
        record.save(update_fields=["response_status", "response_body", "updated_at"])
    return response


def _replay(ctx: RequestContext, key: str, endpoint: str, fingerprint: str) -> Response:
    existing = IdempotencyKey.objects.get(organization=ctx.organization, key=key)
    if (
        existing.user_id != ctx.user.pk
        or existing.endpoint != endpoint
        or existing.request_hash != fingerprint
    ):
        raise IdempotencyKeyReused(
            "This Idempotency-Key was already used for a different request. "
            "Use a new key for a new operation."
        )
    return Response(
        existing.response_body,
        status=existing.response_status or status.HTTP_200_OK,
        headers={REPLAYED_HEADER: "true"},
    )


def _bound_lock_wait() -> None:
    # Applies to this transaction only: a duplicate waits at most this long.
    timeout_ms = int(settings.IDEMPOTENCY_LOCK_TIMEOUT.total_seconds() * 1000)
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = {timeout_ms}")


_H = TypeVar("_H", bound=Callable[..., Response])


def idempotent(*, required: bool) -> Callable[[_H], _H]:
    """Decorate a TenantAPIView handler (``post``) to make it retry-safe."""

    def decorator(handler: _H) -> _H:
        @functools.wraps(handler)
        def wrapper(view: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            route = request.resolver_match.route if request.resolver_match else request.path
            return run_idempotent(
                request,
                get_request_context(request),
                f"{request.method} {route}",
                lambda: handler(view, request, *args, **kwargs),
                required=required,
            )

        parameter = OpenApiParameter(
            HEADER,
            OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
            required=required,
            description="Unique per operation (e.g. a UUID). Retries with the same key "
            "return the original response instead of repeating the operation.",
        )
        return extend_schema(parameters=[parameter])(wrapper)  # type: ignore[return-value]

    return decorator
