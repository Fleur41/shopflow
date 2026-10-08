"""Writing audit records. Call from services, inside the business transaction."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import AuditLog


@dataclass(frozen=True)
class AuditActor:
    """Who is acting, and from where. Built from the request context."""

    organization_id: uuid.UUID
    user_id: uuid.UUID | None
    request_id: str = ""
    ip_address: str | None = None
    user_agent: str = ""


def record_audit(
    actor: AuditActor,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str,
    changes: Mapping[str, Any] | None = None,
    reason: str = "",
    store_id: uuid.UUID | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        organization_id=actor.organization_id,
        store_id=store_id,
        actor_id=actor.user_id,
        actor_type=AuditLog.ActorType.USER if actor.user_id else AuditLog.ActorType.SYSTEM,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        changes=dict(changes or {}),
        reason=reason,
        request_id=actor.request_id[:64],
        ip_address=actor.ip_address,
        user_agent=actor.user_agent[:256],
    )


def diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[Any]]:
    """``{field: [old, new]}`` for every field whose value changed."""
    return {
        field: [_plain(before.get(field)), _plain(after.get(field))]
        for field in sorted(set(before) | set(after))
        if before.get(field) != after.get(field)
    }


def _plain(value: Any) -> Any:
    """Make values JSON-safe for the ``changes`` column."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, set | frozenset | tuple):
        return sorted(_plain(item) for item in value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
