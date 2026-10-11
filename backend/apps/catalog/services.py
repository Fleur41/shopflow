"""Catalog master-data rules beyond the generic ones in ``master_data``: the category tree."""

import uuid
from typing import Any

from django.db import connection, transaction
from rest_framework import status

from apps.common.errors import ApplicationError
from apps.organizations import master_data
from apps.organizations.context import RequestContext

from .models import Category


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
