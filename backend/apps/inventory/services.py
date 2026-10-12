"""Inventory use cases. ``apply_movements`` is the only code that changes stock.

Locking: stock levels are locked ``FOR UPDATE`` in product-id order, so two
transactions touching the same products always queue in the same order and
can't deadlock; the second sees the first's result (docs/DATABASE.md §5,
invariants 3, 6 and 10).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.audit.services import record_audit
from apps.catalog.models import Product, ProductPriceHistory
from apps.common.errors import ApplicationError, StaleVersion
from apps.organizations.access import require_permission
from apps.organizations.context import RequestContext
from apps.organizations.models import Store

from .models import InventoryMovement, StockAdjustment, StockAdjustmentLine, StockLevel

MONEY_PLACES = Decimal("0.0001")

# Adjustment reason → movement type. Reasons that only ever remove (or only
# ever add) stock are checked against the sign of each line.
REASON_MOVEMENT = {
    StockAdjustment.Reason.OPENING_BALANCE: InventoryMovement.Type.OPENING,
    StockAdjustment.Reason.DAMAGED: InventoryMovement.Type.DAMAGED,
    StockAdjustment.Reason.EXPIRED: InventoryMovement.Type.EXPIRED,
}
REMOVES_STOCK = {
    StockAdjustment.Reason.DAMAGED,
    StockAdjustment.Reason.EXPIRED,
    StockAdjustment.Reason.THEFT_LOSS,
}
ADDS_STOCK = {StockAdjustment.Reason.FOUND}


class InsufficientStock(ApplicationError):
    code = "INSUFFICIENT_STOCK"
    title = "Not enough stock"


class InventoryRuleViolation(ApplicationError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "BUSINESS_RULE_VIOLATION"
    title = "The stock change could not be made"


class InvalidQuantity(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"
    title = "Invalid request"


@dataclass(frozen=True)
class MovementLine:
    """One stock change for ``apply_movements``. ``source`` names the document
    field on ``InventoryMovement`` (e.g. ``{"adjustment_line": line}``)."""

    product: Product
    quantity: Decimal  # signed: negative takes stock out
    movement_type: str
    source: dict[str, Any] = field(default_factory=dict)
    unit_cost: Decimal | None = None
    pointer: str = ""  # where an error about this line points in the request


def format_quantity(value: Decimal) -> str:
    """``Decimal("2.000")`` → ``"2"``, ``Decimal("1.250")`` → ``"1.25"``."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def check_quantity(product: Product, quantity: Decimal, pointer: str) -> None:
    """Whole numbers only, unless the product's unit allows fractions."""
    if quantity != quantity.to_integral_value() and not product.unit.allows_fraction:
        raise InvalidQuantity(
            "One or more fields are invalid.",
            errors=[
                {
                    "pointer": pointer,
                    "code": "FRACTION_NOT_ALLOWED",
                    "detail": f"{product.name} is sold in whole {product.unit.name.lower()}.",
                }
            ],
        )


def lock_levels(
    ctx: RequestContext, store: Store, product_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, StockLevel]:
    """Lock (creating if needed) the stock levels of ``product_ids`` in ``store``,
    in product-id order. Must run inside a transaction."""
    ids = sorted(set(product_ids))
    levels = StockLevel.objects.for_org(ctx.organization).filter(store=store, product_id__in=ids)
    missing = set(ids) - set(levels.values_list("product_id", flat=True))
    if missing:
        StockLevel.unscoped.bulk_create(
            [
                StockLevel(organization=ctx.organization, store=store, product_id=pid)
                for pid in missing
            ],
            ignore_conflicts=True,  # created by a concurrent transaction: fine
        )
    locked = levels.select_for_update().order_by("product_id")
    return {level.product_id: level for level in locked}


def apply_movements(
    ctx: RequestContext,
    store: Store,
    lines: list[MovementLine],
    *,
    occurred_at: datetime,
) -> list[InventoryMovement]:
    """Change stock levels and record a movement for each line, atomically.

    Raises ``InsufficientStock`` (listing every short line) if a level would
    go below zero in a store that doesn't allow it for that product.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("apply_movements must run inside a transaction")
    for line in lines:
        if not line.product.track_inventory:
            raise InventoryRuleViolation(
                f"{line.product.name} is not a stocked item.",
                errors=[{"pointer": line.pointer, "code": "NOT_STOCKED"}],
            )
    levels = lock_levels(ctx, store, (line.product.pk for line in lines))

    # Check the end result per product before writing anything.
    change: dict[uuid.UUID, Decimal] = {}
    for line in lines:
        change[line.product.pk] = change.get(line.product.pk, Decimal(0)) + line.quantity
    short = []
    for line in lines:
        level = levels[line.product.pk]
        after = level.quantity_on_hand + change[line.product.pk]
        if after < 0 and line.quantity < 0 and not level.allow_negative:
            short.append((line, level))
    if short:
        raise _insufficient(short)

    movements = []
    for line in lines:
        level = levels[line.product.pk]
        before = level.quantity_on_hand
        after = before + line.quantity
        if line.unit_cost is not None and line.quantity > 0:
            level.average_cost = _weighted_cost(level, line.quantity, line.unit_cost)
        level.quantity_on_hand = after
        level.last_movement_seq += 1
        movements.append(
            InventoryMovement(
                organization=ctx.organization,
                store=store,
                product=line.product,
                movement_type=line.movement_type,
                quantity=line.quantity,
                quantity_before=before,
                quantity_after=after,
                unit_cost=line.unit_cost,
                seq=level.last_movement_seq,
                performed_by=ctx.user,
                occurred_at=occurred_at,
                **line.source,
            )
        )
    InventoryMovement.unscoped.bulk_create(movements)
    for level in {line.product.pk: levels[line.product.pk] for line in lines}.values():
        level.save(update_fields=["quantity_on_hand", "average_cost", "last_movement_seq"])
    return movements


def _weighted_cost(level: StockLevel, quantity: Decimal, unit_cost: Decimal) -> Decimal:
    on_hand = max(level.quantity_on_hand, Decimal(0))
    if level.average_cost is None or on_hand == 0:
        return unit_cost.quantize(MONEY_PLACES)
    total = on_hand * level.average_cost + quantity * unit_cost
    return Decimal(total / (on_hand + quantity)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _insufficient(short: list[tuple[MovementLine, StockLevel]]) -> InsufficientStock:
    errors: list[dict[str, Any]] = []
    for line, level in short:
        unit = line.product.unit.name.lower()
        errors.append(
            {
                "pointer": line.pointer,
                "code": "INSUFFICIENT_STOCK",
                "detail": f"{line.product.name}: {format_quantity(level.quantity_on_hand)} "
                f"{unit} in stock, {format_quantity(-line.quantity)} needed.",
                "meta": {
                    "product_id": str(line.product.pk),
                    "product_name": line.product.name,
                    "available": format_quantity(level.quantity_on_hand),
                    "requested": format_quantity(-line.quantity),
                },
            }
        )
    first = errors[0]["meta"]
    if len(errors) == 1:
        detail = (
            f'"{first["product_name"]}" only has {first["available"]} in stock, but '
            f"{first['requested']} are needed. Reduce the quantity or update the stock."
        )
    else:
        detail = (
            f"{len(errors)} items don't have enough stock. "
            "Reduce the quantities or update the stock."
        )
    return InsufficientStock(detail, errors=errors)


# --- Adjustments and opening balances -------------------------------------------------


@dataclass(frozen=True)
class AdjustmentLineInput:
    product: Product
    quantity_delta: Decimal | None = None
    counted_quantity: Decimal | None = None
    unit_cost: Decimal | None = None  # opening balances only


def create_adjustment(
    ctx: RequestContext,
    store: Store,
    *,
    client_txn_id: uuid.UUID,
    reason_code: str,
    lines: list[AdjustmentLineInput],
    note: str = "",
    occurred_at: datetime | None = None,
) -> StockAdjustment:
    """Record a stock adjustment (or opening balance) and its movements.

    A line gives either the change (``quantity_delta``) or what was counted
    (``counted_quantity``), in which case the change is computed against the
    locked stock level. Sending the same ``client_txn_id`` again returns the
    first adjustment unchanged.
    """
    reason = StockAdjustment.Reason(reason_code)
    with transaction.atomic():
        existing = (
            StockAdjustment.objects.for_org(ctx.organization)
            .filter(client_txn_id=client_txn_id)
            .first()
        )
        if existing is not None:
            return existing
        if reason == StockAdjustment.Reason.OTHER and not note.strip():
            raise _line_error("/note", "REQUIRED", "Say what happened when the reason is Other.")
        for index, line in enumerate(lines):
            for value in (line.quantity_delta, line.counted_quantity):
                if value is not None:
                    check_quantity(line.product, value, f"/lines/{index}")

        levels = lock_levels(ctx, store, (line.product.pk for line in lines))
        deltas = []
        for index, line in enumerate(lines):
            level = levels[line.product.pk]
            if reason == StockAdjustment.Reason.OPENING_BALANCE and level.last_movement_seq:
                raise InventoryRuleViolation(
                    f"{line.product.name} already has stock history in this store. "
                    "Use a stock count instead.",
                    errors=[{"pointer": f"/lines/{index}", "code": "OPENING_BALANCE_EXISTS"}],
                )
            if line.counted_quantity is not None:
                delta = line.counted_quantity - level.quantity_on_hand
            else:
                delta = line.quantity_delta or Decimal(0)
            if (reason in REMOVES_STOCK and delta > 0) or (reason in ADDS_STOCK and delta < 0):
                raise _line_error(
                    f"/lines/{index}",
                    "WRONG_DIRECTION",
                    f"{reason.label} can only "
                    f"{'remove' if reason in REMOVES_STOCK else 'add'} stock.",
                )
            deltas.append(delta)

        adjustment = StockAdjustment.objects.create(
            organization=ctx.organization,
            store=store,
            reason_code=reason,
            note=note.strip(),
            client_txn_id=client_txn_id,
            created_by=ctx.user,
            occurred_at=occurred_at or timezone.now(),
        )
        movement_type = REASON_MOVEMENT.get(reason, InventoryMovement.Type.ADJUSTMENT)
        movement_lines = []
        for line, delta in zip(lines, deltas, strict=True):
            adjustment_line = StockAdjustmentLine.objects.create(
                organization=ctx.organization,
                adjustment=adjustment,
                product=line.product,
                quantity_delta=delta,
                counted_quantity=line.counted_quantity,
            )
            if delta != 0:  # a count that matched records the line, but moves nothing
                movement_lines.append(
                    MovementLine(
                        product=line.product,
                        quantity=delta,
                        movement_type=movement_type,
                        source={"adjustment_line": adjustment_line},
                        unit_cost=line.unit_cost,
                    )
                )
        apply_movements(ctx, store, movement_lines, occurred_at=adjustment.occurred_at)
        record_audit(
            ctx.audit_actor,
            action="stock_adjustment.created",
            entity_type="stock_adjustment",
            entity_id=adjustment.pk,
            store_id=store.pk,
            reason=adjustment.note,
            changes={
                "reason_code": [None, reason.value],
                "lines": [
                    None,
                    [
                        {"product": str(line.product.pk), "delta": format_quantity(delta)}
                        for line, delta in zip(lines, deltas, strict=True)
                    ],
                ],
            },
        )
    return adjustment


def _line_error(pointer: str, code: str, detail: str) -> InvalidQuantity:
    return InvalidQuantity(
        "One or more fields are invalid.",
        errors=[{"pointer": pointer, "code": code, "detail": detail}],
    )


# --- Per-store settings -------------------------------------------------------------------

SETTING_PERMISSIONS = {
    "reorder_level": "inventory.manage_levels",
    "min_stock": "inventory.manage_levels",
    "max_stock": "inventory.manage_levels",
    "selling_price_override": "products.change_price",
    "allow_negative": "stores.manage_inventory_policy",
}


def update_stock_settings(
    ctx: RequestContext, store: Store, product: Product, *, version: int, **changes: Any
) -> StockLevel:
    """Change a product's settings in one store. Each field needs its own permission;
    a store price change is also written to price history."""
    for name in changes:
        require_permission(ctx, SETTING_PERMISSIONS[name])
    with transaction.atomic():
        level = lock_levels(ctx, store, [product.pk])[product.pk]
        if level.version != version:
            raise StaleVersion("Someone else changed this. Reload and try again.")
        before = {name: getattr(level, name) for name in changes}
        for name, value in changes.items():
            setattr(level, name, value)
        if (
            level.min_stock is not None
            and level.max_stock is not None
            and level.min_stock > level.max_stock
        ):
            raise _line_error("/min_stock", "MIN_ABOVE_MAX", "Minimum can't be above maximum.")
        changed = {
            name: [_jsonable(before[name]), _jsonable(value)]
            for name, value in changes.items()
            if before[name] != value
        }
        if not changed:
            return level
        level.version += 1
        level.save(update_fields=[*changes, "version"])
        if "selling_price_override" in changed:
            old = before["selling_price_override"]
            ProductPriceHistory.objects.create(
                organization=ctx.organization,
                product=product,
                store=store,
                old_price=old if old is not None else product.selling_price,
                new_price=level.selling_price_override
                if level.selling_price_override is not None
                else product.selling_price,
                changed_by=ctx.user,
            )
        record_audit(
            ctx.audit_actor,
            action="stock_level.updated",
            entity_type="product",
            entity_id=product.pk,
            store_id=store.pk,
            changes=changed,
        )
    return level


def _jsonable(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value
