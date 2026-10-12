"""Read-side queries for store inventory."""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db.models import (
    Case,
    DecimalField,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from apps.catalog.models import Product, ProductIdentifier
from apps.common.fields import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.organizations.context import RequestContext
from apps.organizations.models import Store
from apps.suppliers.models import ProductSupplier

from .models import StockLevel

_QUANTITY: "DecimalField[Any, Any]" = DecimalField(max_digits=14, decimal_places=3)
_MONEY: "DecimalField[Any, Any]" = DecimalField(
    max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
)

STOCK_STATUSES = ("out", "low", "ok")


def effective_price(product: Product, level: StockLevel | None) -> Decimal:
    """What the product sells for in this store."""
    if level is not None and level.selling_price_override is not None:
        return Decimal(level.selling_price_override)
    return Decimal(product.selling_price)


def stocked_products(ctx: RequestContext, store: Store) -> QuerySet[Product]:
    """Stocked products with this store's level, settings and stock status.

    A product with no stock level yet has none in this store: it shows as 0.
    """
    level = StockLevel.objects.for_org(ctx.organization).filter(store=store, product=OuterRef("pk"))

    def from_level(name: str, output: "DecimalField[Any, Any]") -> Subquery:
        return Subquery(level.values(name)[:1], output_field=output)

    return (
        Product.objects.for_org(ctx.organization)
        .filter(track_inventory=True)
        .select_related("unit", "category")
        .annotate(
            quantity_on_hand=Coalesce(
                from_level("quantity_on_hand", _QUANTITY), Value(Decimal(0)), output_field=_QUANTITY
            ),
            store_reorder_level=from_level("reorder_level", _QUANTITY),
            effective_reorder_level=Coalesce(
                from_level("reorder_level", _QUANTITY),
                F("default_reorder_level"),
                output_field=_QUANTITY,
            ),
            min_stock=from_level("min_stock", _QUANTITY),
            max_stock=from_level("max_stock", _QUANTITY),
            average_cost=from_level("average_cost", _MONEY),
            selling_price_override=from_level("selling_price_override", _MONEY),
            allow_negative=Coalesce(Subquery(level.values("allow_negative")[:1]), Value(False)),
            level_version=Coalesce(Subquery(level.values("version")[:1]), Value(1)),
        )
        .annotate(
            stock_status=Case(
                When(quantity_on_hand__lte=0, then=Value("out")),
                When(
                    effective_reorder_level__isnull=False,
                    quantity_on_hand__lte=F("effective_reorder_level"),
                    then=Value("low"),
                ),
                default=Value("ok"),
            )
        )
    )


def filter_stocked(
    products: QuerySet[Product],
    *,
    search: str = "",
    category: uuid.UUID | None = None,
    supplier: uuid.UUID | None = None,
    stock_status: str = "",
    is_active: bool | None = None,
) -> QuerySet[Product]:
    if search:
        products = products.filter(
            Q(name__icontains=search) | Q(sku__iexact=search) | Q(identifiers__value=search)
        ).distinct()
    if category:
        products = products.filter(category_id=category)
    if supplier:
        products = products.filter(
            pk__in=ProductSupplier.unscoped.filter(supplier_id=supplier).values("product_id")
        )
    if stock_status in STOCK_STATUSES:
        products = products.filter(Q(stock_status=stock_status))  # an annotation
    if is_active is not None:
        products = products.filter(is_active=is_active)
    return products


@dataclass(frozen=True)
class Lookup:
    product: Product
    pack_quantity: Decimal
    level: StockLevel | None


def lookup_code(ctx: RequestContext, store: Store, code: str) -> Lookup | None:
    """The hot path at the till: a scanned or typed code → product, pack size, stock.

    An identifier (barcode) matches exactly; otherwise the SKU, ignoring case.
    """
    code = code.strip()
    if not code:
        return None
    identifier = (
        ProductIdentifier.objects.for_org(ctx.organization)
        .filter(value=code)
        .select_related("product__unit", "product__tax_rate")
        .first()
    )
    if identifier is not None:
        product, pack = identifier.product, identifier.pack_quantity
    else:
        found = (
            Product.objects.for_org(ctx.organization)
            .filter(sku__iexact=code)
            .select_related("unit", "tax_rate")
            .first()
        )
        if found is None:
            return None
        product, pack = found, Decimal(1)
    level = (
        StockLevel.objects.for_org(ctx.organization).filter(store=store, product=product).first()
    )
    return Lookup(product=product, pack_quantity=pack, level=level)
