"""Catalog master-data rules beyond the generic ones in ``master_data``: the
category tree, and the units and tax rates every new business starts with."""

import uuid
from decimal import Decimal
from typing import Any

from django.db import connection, transaction
from rest_framework import status

from apps.audit.services import AuditActor, record_audit
from apps.common.errors import ApplicationError
from apps.organizations import master_data
from apps.organizations.context import RequestContext
from apps.organizations.models import Organization

from .models import Category, TaxRate, UnitOfMeasure

# code, name, allows fraction, KRA unit of quantity
DEFAULT_UNITS = [
    ("PCS", "Pieces", False, "U"),
    ("KG", "Kilogram", True, "KG"),
    ("L", "Litre", True, "LTR"),
]
# Kenya-first defaults (Q-1), only for businesses trading in KES. Name, rate, eTIMS type.
KENYA_TAX_RATES = [
    ("VAT 16%", Decimal("0.16"), "B"),
    ("VAT 8%", Decimal("0.08"), "E"),
    ("Zero-rated", Decimal("0"), "C"),
    ("Exempt", Decimal("0"), "A"),
]


class CategoryCycle(ApplicationError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "CATEGORY_CYCLE"
    title = "Invalid parent category"


def update_category(
    ctx: RequestContext, category: Category, *, version: int, **changes: Any
) -> Category:
    if "parent" not in changes:
        return master_data.update_entry(ctx, category, version=version, **changes)
    with transaction.atomic():
        _lock_category_tree(ctx)
        return master_data.update_entry(
            ctx, category, version=version, check=_require_valid_parent, **changes
        )


def _lock_category_tree(ctx: RequestContext) -> None:
    """Serialize re-parenting within a business, so two concurrent moves
    (A under B, B under A) cannot together create a cycle."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"catalog.category_tree:{ctx.organization.pk}"],
        )


def _require_valid_parent(category: Category, changes: dict[str, Any]) -> None:
    """A category can't move inside itself or one of its subcategories."""
    parent: Category | None = changes["parent"]
    ancestor_id: uuid.UUID | None = parent.pk if parent is not None else None
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


def create_default_catalog(organization: Organization, actor: AuditActor) -> None:
    """Called by sign-up, inside its transaction. Other currencies get a single
    "No tax" rate: we don't guess another country's taxes."""
    entries: list[UnitOfMeasure | TaxRate] = [
        UnitOfMeasure(
            organization=organization,
            code=code,
            name=name,
            allows_fraction=fraction,
            etims_quantity_unit=kra_unit,
        )
        for code, name, fraction, kra_unit in DEFAULT_UNITS
    ]
    rates = (
        KENYA_TAX_RATES if organization.base_currency == "KES" else [("No tax", Decimal("0"), "")]
    )
    entries += [
        TaxRate(organization=organization, name=name, rate=rate, etims_tax_type=tax_type)
        for name, rate, tax_type in rates
    ]
    for entry in entries:
        entry.save()
        record_audit(
            actor,
            action=f"{entry.audit_name}.created",
            entity_type=entry.audit_name,
            entity_id=entry.pk,
            changes={"name": [None, entry.name]},
        )
