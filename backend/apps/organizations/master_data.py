"""Master data: an organization's lookup records, such as categories or payment methods.

They are never deleted, only deactivated, and carry a ``version`` for
optimistic locking (docs/DATABASE.md §1). Every create and change is audited
in the same transaction.
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, ClassVar

from django.db import IntegrityError, models, transaction
from rest_framework import status

from apps.audit.services import diff, record_audit
from apps.common.errors import ApplicationError, StaleVersion

from .context import RequestContext
from .models import TenantModel


class MasterData(TenantModel):
    # ``entity_type`` in the audit log.
    audit_name: ClassVar[str]
    # Unique constraint → the field it protects. Serializers check first; this
    # turns a request that loses a race into the same field error.
    unique_fields: ClassVar[dict[str, str]] = {}

    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True


def create_entry[E: MasterData](ctx: RequestContext, model: type[E], **fields: Any) -> E:
    with _unique_violations(model), transaction.atomic():
        entry: E = model.objects.create(organization=ctx.organization, **fields)
        record_audit(
            ctx.audit_actor,
            action=f"{model.audit_name}.created",
            entity_type=model.audit_name,
            entity_id=entry.pk,
            changes={field: [None, value] for field, value in audit_values(entry, fields).items()},
        )
    return entry


def update_entry[E: MasterData](
    ctx: RequestContext,
    entry: E,
    *,
    version: int,
    check: Callable[[E, dict[str, Any]], None] | None = None,
    **changes: Any,
) -> E:
    """Apply ``changes`` if nobody else changed the entry since ``version``.

    ``check`` runs on the locked, current entry before anything is written.
    """
    model = type(entry)
    with _unique_violations(model), transaction.atomic():
        entry = model.objects.for_org(ctx.organization).select_for_update().get(pk=entry.pk)
        if entry.version != version:
            raise StaleVersion("Someone else changed this. Reload and try again.")
        if check is not None:
            check(entry, changes)

        before = audit_values(entry, changes)
        for field, value in changes.items():
            setattr(entry, field, value)
        changed = diff(before, audit_values(entry, changes))
        if changed:
            entry.version += 1
            entry.save()
            record_audit(
                ctx.audit_actor,
                action=f"{model.audit_name}.updated",
                entity_type=model.audit_name,
                entity_id=entry.pk,
                changes=changed,
            )
    return entry


def audit_values(entry: models.Model, fields: Any) -> dict[str, Any]:
    """Audit-friendly values: related objects by ID, decimals as strings at the
    field's precision (so "60.00" from a request equals the stored "60.0000")."""
    values: dict[str, Any] = {}
    for name in fields:
        field = entry._meta.get_field(name)
        value = getattr(entry, field.attname if isinstance(field, models.ForeignKey) else name)
        if isinstance(field, models.DecimalField) and value is not None:
            value = Decimal(value).quantize(Decimal(1).scaleb(-(field.decimal_places or 0)))
        values[name] = str(value) if isinstance(value, Decimal | uuid.UUID) else value
    return values


@contextmanager
def _unique_violations(model: type[MasterData]) -> Iterator[None]:
    try:
        yield
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        field = model.unique_fields.get(getattr(diag, "constraint_name", None) or "")
        if field is None:
            raise
        raise ApplicationError(
            "One or more fields are invalid.",
            code="VALIDATION_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid request",
            errors=[{"pointer": f"/{field}", "code": "TAKEN", "detail": "This is already in use."}],
        ) from exc
