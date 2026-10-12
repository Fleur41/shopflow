"""Store inventory: stock levels, the movements that change them, and adjustments.

Every change to a stock level is an append-only ``InventoryMovement`` that
points at the document that caused it, written by one service
(``apps.inventory.services.apply_movements``) under row locks taken in a fixed
order (docs/DATABASE.md §2.2, §5). The database checks the arithmetic of each
movement and that stock never goes negative unless the store allows it.
"""

from typing import Any, ClassVar

from django.conf import settings
from django.db import models

from apps.audit.models import AppendOnlyError
from apps.common.fields import MoneyField, QuantityField
from apps.organizations.models import TenantManager, TenantModel

ADJUSTMENT_REASONS = [
    "OPENING_BALANCE",
    "COUNT_CORRECTION",
    "DAMAGED",
    "EXPIRED",
    "THEFT_LOSS",
    "FOUND",
    "OTHER",
]
MOVEMENT_TYPES = [
    "PURCHASE",
    "SALE",
    "SALE_RETURN",
    "PURCHASE_RETURN",
    "ADJUSTMENT",
    "DAMAGED",
    "EXPIRED",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "OPENING",
]


class StockLevel(TenantModel):
    """How much of a product a store holds, plus its per-store settings.

    Only ``apply_movements`` changes ``quantity_on_hand``. Settings (reorder
    levels, price override, negative-stock policy) are versioned for PATCH.
    """

    objects: ClassVar[TenantManager["StockLevel"]]

    store = models.ForeignKey("organizations.Store", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity_on_hand = QuantityField(default=0)
    average_cost = MoneyField(null=True, blank=True)
    selling_price_override = MoneyField(
        null=True, blank=True, help_text="This store's price, if it differs from the product's."
    )
    reorder_level = QuantityField(
        null=True, blank=True, help_text="Empty: use the product's default reorder level."
    )
    min_stock = QuantityField(null=True, blank=True)
    max_stock = QuantityField(null=True, blank=True)
    allow_negative = models.BooleanField(
        default=False, help_text="Let sales take stock below zero (to be counted later)."
    )
    # Movements of this product in this store are numbered 1, 2, 3, ...
    last_movement_seq = models.BigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    row_version = models.BigIntegerField(default=0, editable=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["store", "product"], name="inventory_stock_level_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(allow_negative=True) | models.Q(quantity_on_hand__gte=0),
                name="inventory_stock_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(selling_price_override__isnull=True)
                | models.Q(selling_price_override__gte=0),
                name="inventory_price_override_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reorder_level__isnull=True) | models.Q(reorder_level__gte=0),
                name="inventory_reorder_level_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(min_stock__isnull=True)
                | models.Q(max_stock__isnull=True)
                | models.Q(min_stock__lte=models.F("max_stock")),
                name="inventory_min_not_above_max",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["row_version"], name="inventory_stock_row_ver_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.quantity_on_hand}"


class StockAdjustment(TenantModel):
    """A counted or written-off change to stock, with a reason. Also used for a
    product's opening balance in a store."""

    class Reason(models.TextChoices):
        OPENING_BALANCE = "OPENING_BALANCE", "Opening stock"
        COUNT_CORRECTION = "COUNT_CORRECTION", "Stock count"
        DAMAGED = "DAMAGED", "Damaged"
        EXPIRED = "EXPIRED", "Expired"
        THEFT_LOSS = "THEFT_LOSS", "Theft or loss"
        FOUND = "FOUND", "Found"
        OTHER = "OTHER", "Other"

    objects: ClassVar[TenantManager["StockAdjustment"]]

    store = models.ForeignKey("organizations.Store", on_delete=models.PROTECT, related_name="+")
    reason_code = models.CharField(max_length=20, choices=Reason.choices)
    note = models.CharField(max_length=500, blank=True)
    client_txn_id = models.UUIDField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    occurred_at = models.DateTimeField()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "client_txn_id"], name="inventory_adjustment_txn_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(reason_code__in=ADJUSTMENT_REASONS),
                name="inventory_adjustment_reason_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason_code="OTHER") | ~models.Q(note=""),
                name="inventory_adjustment_other_needs_note",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["store", "occurred_at"], name="inventory_adjustment_store_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.reason_code} {self.occurred_at:%Y-%m-%d}"


class StockAdjustmentLine(TenantModel):
    objects: ClassVar[TenantManager["StockAdjustmentLine"]]

    adjustment = models.ForeignKey(StockAdjustment, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity_delta = QuantityField()
    counted_quantity = QuantityField(
        null=True, blank=True, help_text="Set when the line came from a count."
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["adjustment", "product"], name="inventory_adjustment_line_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity_delta}"


class InventoryMovement(TenantModel):
    """One change to one stock level. Append-only: corrections are new movements."""

    class Type(models.TextChoices):
        PURCHASE = "PURCHASE", "Purchase"
        SALE = "SALE", "Sale"
        SALE_RETURN = "SALE_RETURN", "Sale return"
        PURCHASE_RETURN = "PURCHASE_RETURN", "Return to supplier"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"
        DAMAGED = "DAMAGED", "Damaged"
        EXPIRED = "EXPIRED", "Expired"
        TRANSFER_IN = "TRANSFER_IN", "Transfer in"
        TRANSFER_OUT = "TRANSFER_OUT", "Transfer out"
        OPENING = "OPENING", "Opening stock"

    # The runtime database role gets no UPDATE/DELETE here (apps.common.db_grants).
    append_only = True
    objects: ClassVar[TenantManager["InventoryMovement"]]

    store = models.ForeignKey("organizations.Store", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    movement_type = models.CharField(max_length=20, choices=Type.choices)
    quantity = QuantityField()
    quantity_before = QuantityField()
    quantity_after = QuantityField()
    unit_cost = MoneyField(null=True, blank=True)
    seq = models.BigIntegerField(help_text="Position in this product's history in this store.")
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    # The document that caused the movement: exactly one is set (see the CHECK).
    adjustment_line = models.ForeignKey(
        StockAdjustmentLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movements",
    )
    sale_item = models.ForeignKey(
        "sales.SaleItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movements",
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0), name="inventory_movement_quantity_not_zero"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    quantity_after=models.F("quantity_before") + models.F("quantity")
                ),
                name="inventory_movement_arithmetic",
            ),
            models.CheckConstraint(
                condition=models.Q(movement_type__in=MOVEMENT_TYPES),
                name="inventory_movement_type_valid",
            ),
            # Exactly one source document, of the kind the movement type expects.
            models.CheckConstraint(
                condition=models.Q(
                    movement_type__in=["ADJUSTMENT", "DAMAGED", "EXPIRED", "OPENING"],
                    adjustment_line__isnull=False,
                    sale_item__isnull=True,
                )
                | models.Q(
                    movement_type="SALE", sale_item__isnull=False, adjustment_line__isnull=True
                ),
                name="inventory_movement_source",
            ),
            models.UniqueConstraint(
                fields=["store", "product", "seq"], name="inventory_movement_seq_unique"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "recorded_at"], name="inventory_movement_org_idx"),
            models.Index(fields=["store", "occurred_at"], name="inventory_movement_store_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.movement_type} {self.quantity}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Inventory movements cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise AppendOnlyError("Inventory movements cannot be deleted.")
