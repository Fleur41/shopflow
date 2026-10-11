"""Product use cases (docs/API.md §4.3). Every change is audited in the same transaction.

- A missing SKU is generated (``P000001``, ``P000002``, …) per business.
- Changing a selling price needs ``products.change_price`` and writes price history.
- A code that finds a product at the till (an identifier value or a SKU) maps
  to exactly one product per business. The database enforces this within each
  table; this module enforces it across the two.
"""

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, connection, transaction
from rest_framework import status

from apps.audit.services import record_audit
from apps.common.errors import ApplicationError
from apps.organizations import master_data
from apps.organizations.access import require_permission
from apps.organizations.context import RequestContext

from .models import Product, ProductIdentifier, ProductPriceHistory

GENERATED_SKU_PREFIX = "P"


class CodeInUse(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"
    title = "Invalid request"


def create_product(
    ctx: RequestContext, *, identifiers: list[dict[str, Any]] | None = None, **fields: Any
) -> Product:
    with transaction.atomic():
        if not fields.get("sku"):
            fields["sku"] = _next_sku(ctx)
        _require_code_free(ctx, fields["sku"], pointer="/sku")
        product = master_data.create_entry(ctx, Product, **fields)
        _record_price(ctx, product, old=None, new=product.selling_price)
        for index, identifier in enumerate(identifiers or []):
            add_identifier(ctx, product, pointer=f"/identifiers/{index}/value", **identifier)
    return product


def update_product(
    ctx: RequestContext, product: Product, *, version: int, **changes: Any
) -> Product:
    old_price: list[Decimal] = []

    def check(current: Product, changes: dict[str, Any]) -> None:
        new_price = changes.get("selling_price")
        if new_price is not None and new_price != current.selling_price:
            require_permission(ctx, "products.change_price")
            old_price.append(current.selling_price)
        if "sku" in changes and changes["sku"].lower() != current.sku.lower():
            _require_code_free(ctx, changes["sku"], pointer="/sku", product=current)

    with transaction.atomic():
        product = master_data.update_entry(ctx, product, version=version, check=check, **changes)
        if old_price:
            _record_price(ctx, product, old=old_price[0], new=product.selling_price)
    return product


def add_identifier(
    ctx: RequestContext, product: Product, *, pointer: str = "/value", **fields: Any
) -> ProductIdentifier:
    with transaction.atomic():
        # Serialize identifier changes per product, so "make primary" can't race.
        Product.objects.for_org(ctx.organization).select_for_update().get(pk=product.pk)
        _require_code_free(ctx, fields["value"], pointer=pointer, product=product)
        existing = ProductIdentifier.objects.for_org(ctx.organization).filter(product=product)
        if not existing.exists():
            fields["is_primary"] = True  # the first code is the one printed on labels
        elif fields.get("is_primary"):
            existing.filter(is_primary=True).update(is_primary=False)
        try:
            with transaction.atomic():
                identifier = ProductIdentifier.objects.create(
                    organization=ctx.organization, product=product, **fields
                )
        except IntegrityError as exc:  # another request added the same code just now
            raise _code_in_use(pointer, "another product") from exc
        record_audit(
            ctx.audit_actor,
            action="product_identifier.added",
            entity_type=Product.audit_name,
            entity_id=product.pk,
            changes={"identifier": [None, identifier.value]},
        )
    return identifier


def remove_identifier(ctx: RequestContext, identifier: ProductIdentifier) -> None:
    with transaction.atomic():
        Product.objects.for_org(ctx.organization).select_for_update().get(pk=identifier.product_id)
        identifier.delete()
        if identifier.is_primary:
            successor = (
                ProductIdentifier.objects.for_org(ctx.organization)
                .filter(product_id=identifier.product_id)
                .order_by("id")
                .first()
            )
            if successor is not None:
                successor.is_primary = True
                successor.save(update_fields=["is_primary"])
        record_audit(
            ctx.audit_actor,
            action="product_identifier.removed",
            entity_type=Product.audit_name,
            entity_id=identifier.product_id,
            changes={"identifier": [identifier.value, None]},
        )


def _record_price(
    ctx: RequestContext, product: Product, *, old: Decimal | None, new: Decimal
) -> None:
    ProductPriceHistory.objects.create(
        organization=ctx.organization,
        product=product,
        old_price=old,
        new_price=new,
        changed_by=ctx.user,
    )


def _require_code_free(
    ctx: RequestContext, code: str, *, pointer: str, product: Product | None = None
) -> None:
    """Refuse ``code`` if the till could find a different product, or the same
    identifier twice, with it.

    A SKU (``pointer == "/sku"``) may not match another product's SKU or
    identifiers. An identifier may not match another product's SKU or any
    identifier at all, including one of the same product.
    """
    is_sku = pointer == "/sku"
    skus = Product.objects.for_org(ctx.organization).filter(sku__iexact=code)
    identifiers = ProductIdentifier.objects.for_org(ctx.organization).filter(value=code)
    if product is not None:
        skus = skus.exclude(pk=product.pk)
        if is_sku:
            identifiers = identifiers.exclude(product=product)
    clash = (
        skus.values_list("name", flat=True).first()
        or identifiers.values_list("product__name", flat=True).first()
    )
    if clash is not None:
        raise _code_in_use(pointer, clash)


def _code_in_use(pointer: str, product_name: str) -> CodeInUse:
    return CodeInUse(
        "One or more fields are invalid.",
        errors=[
            {
                "pointer": pointer,
                "code": "CODE_IN_USE",
                "detail": f"This code is already used by {product_name}.",
            }
        ],
    )


def _next_sku(ctx: RequestContext) -> str:
    """The next ``P`` number for this business. Serialized per business, so
    two products created at once never get the same SKU."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"catalog.sku:{ctx.organization.pk}"],
        )
    generated = (
        Product.objects.for_org(ctx.organization)
        .filter(sku__regex=rf"^{GENERATED_SKU_PREFIX}[0-9]{{6,}}$")
        .values_list("sku", flat=True)
    )
    highest = max((int(sku[len(GENERATED_SKU_PREFIX) :]) for sku in generated), default=0)
    return f"{GENERATED_SKU_PREFIX}{highest + 1:06d}"
