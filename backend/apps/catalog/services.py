"""Catalog master-data use cases. Every change is audited in the same transaction."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, connection, models, transaction
from rest_framework import status

from apps.audit.services import diff, record_audit
from apps.common.errors import ApplicationError, StaleVersion
from apps.organizations.context import RequestContext

from .models import CatalogEntry, Category


class CategoryCycle(ApplicationError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "CATEGORY_CYCLE"
    title = "Invalid parent category"


# Unique constraint → the field it protects. The serializers check first; these
# catch two requests racing to use the same name.
_UNIQUE_FIELDS = {
    "catalog_category_name_unique": "name",
    "catalog_brand_name_unique": "name",
    "catalog_unit_code_unique": "code",
    "catalog_tax_rate_name_unique": "name",
}


def create_entry[E: CatalogEntry](ctx: RequestContext, model: type[E], **fields: Any) -> E:
    with _unique_violations(), transaction.atomic():
        entry: E = model.objects.create(organization=ctx.organization, **fields)
        record_audit(
            ctx.audit_actor,
            action=f"{model.audit_name}.created",
            entity_type=model.audit_name,
            entity_id=entry.pk,
            changes={field: [None, value] for field, value in _values(entry, fields).items()},
        )
    return entry


def update_entry[E: CatalogEntry](
    ctx: RequestContext, entry: E, *, version: int, **changes: Any
) -> E:
    """Apply ``changes`` if nobody else changed the entry since ``version``."""
    model = type(entry)
    with _unique_violations(), transaction.atomic():
        if isinstance(entry, Category) and "parent" in changes:
            _lock_category_tree(ctx)
        entry = model.objects.for_org(ctx.organization).select_for_update().get(pk=entry.pk)
        if entry.version != version:
            raise StaleVersion("Someone else changed this. Reload and try again.")
        if isinstance(entry, Category) and changes.get("parent") is not None:
            _require_not_descendant(entry, changes["parent"])

        before = _values(entry, changes)
        for field, value in changes.items():
            setattr(entry, field, value)
        changed = diff(before, _values(entry, changes))
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


@contextmanager
def _unique_violations() -> Iterator[None]:
    try:
        yield
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        field = _UNIQUE_FIELDS.get(getattr(diag, "constraint_name", None) or "")
        if field is None:
            raise
        raise ApplicationError(
            "One or more fields are invalid.",
            code="VALIDATION_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid request",
            errors=[{"pointer": f"/{field}", "code": "TAKEN", "detail": "This is already in use."}],
        ) from exc


def _lock_category_tree(ctx: RequestContext) -> None:
    """Serialize re-parenting within a business, so two concurrent moves
    (A under B, B under A) cannot together create a cycle."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"catalog.category_tree:{ctx.organization.pk}"],
        )


def _require_not_descendant(category: Category, parent: Category) -> None:
    ancestor_id: uuid.UUID | None = parent.pk
    while ancestor_id is not None:
        if ancestor_id == category.pk:
            raise CategoryCycle(
                "A category can't be moved inside itself or one of its subcategories.",
                errors=[{"pointer": "/parent", "code": "CATEGORY_CYCLE"}],
            )
        ancestor_id = (
            Category.objects.for_org(category.organization_id)
            .filter(pk=ancestor_id)
            .values_list("parent_id", flat=True)
            .get()
        )


def _values(entry: CatalogEntry, fields: Any) -> dict[str, Any]:
    """Audit-friendly values: related objects by ID, decimals as strings."""
    values: dict[str, Any] = {}
    for name in fields:
        field = entry._meta.get_field(name)
        value = getattr(entry, field.attname if isinstance(field, models.ForeignKey) else name)
        values[name] = str(value) if isinstance(value, Decimal | uuid.UUID) else value
    return values
