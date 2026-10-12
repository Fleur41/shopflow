"""Sales: what was sold, at what price, and how it was paid (docs/DATABASE.md §2.3).

A completed sale is never edited or deleted; corrections are voids and returns
(Phase 3.6). Product names, SKUs, prices, costs and tax rates are copied onto
each line, so a receipt reprinted years later says what it said on the day.
The part of a sale on customer credit is ``amount_on_credit`` plus a ledger
entry, not a payment: no money moved.
"""

from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.common.fields import CurrencyField, MoneyField, QuantityField
from apps.organizations.models import TenantManager, TenantModel

SALE_STATUSES = ["COMPLETED", "VOIDED"]
SALE_ORIGINS = ["WEB", "MOBILE_ONLINE", "MOBILE_OFFLINE"]


class Sale(TenantModel):
    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        VOIDED = "VOIDED", "Voided"

    class Origin(models.TextChoices):
        WEB = "WEB", "Web till"
        MOBILE_ONLINE = "MOBILE_ONLINE", "Phone, online"
        MOBILE_OFFLINE = "MOBILE_OFFLINE", "Phone, synced later"

    objects: ClassVar[TenantManager["Sale"]]

    store = models.ForeignKey("organizations.Store", on_delete=models.PROTECT, related_name="+")
    receipt_number = models.CharField(max_length=40)
    client_txn_id = models.UUIDField()
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    currency = CurrencyField()
    tax_mode = models.CharField(max_length=10)
    subtotal = MoneyField()
    discount_total = MoneyField()
    tax_total = MoneyField()
    total = MoneyField()
    amount_paid = MoneyField()
    amount_on_credit = MoneyField(default=0)
    change_given = MoneyField(default=0)
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.WEB)
    notes = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField(help_text="When the sale happened at the till.")
    recorded_at = models.DateTimeField(auto_now_add=True, help_text="When the server saved it.")

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["store", "receipt_number"], name="sales_sale_receipt_unique"
            ),
            models.UniqueConstraint(
                fields=["organization", "client_txn_id"], name="sales_sale_txn_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=SALE_STATUSES), name="sales_sale_status_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(origin__in=SALE_ORIGINS), name="sales_sale_origin_valid"
            ),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="sales_sale_total_valid"),
            models.CheckConstraint(
                condition=models.Q(
                    amount_paid__gte=0, amount_on_credit__gte=0, change_given__gte=0
                ),
                name="sales_sale_amounts_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total=models.F("amount_paid") + models.F("amount_on_credit")),
                name="sales_sale_fully_tendered",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_on_credit=0) | models.Q(customer__isnull=False),
                name="sales_sale_credit_has_customer",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["store", "occurred_at"], name="sales_sale_store_time_idx"),
            models.Index(fields=["cashier", "occurred_at"], name="sales_sale_cashier_idx"),
            models.Index(fields=["customer", "occurred_at"], name="sales_sale_customer_idx"),
        ]

    def __str__(self) -> str:
        return self.receipt_number


class SaleItem(TenantModel):
    objects: ClassVar[TenantManager["SaleItem"]]

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="items")
    line_no = models.PositiveSmallIntegerField()
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    product_name = models.CharField(max_length=200)
    sku = models.CharField(max_length=40)
    unit_code = models.CharField(max_length=10)
    scanned_code = models.CharField(max_length=64, blank=True)
    quantity = QuantityField()
    unit_price = MoneyField()
    list_price = MoneyField(help_text="The store's price at the time, before any override.")
    price_overridden = models.BooleanField(default=False)
    override_reason = models.CharField(max_length=200, blank=True)
    unit_cost = MoneyField(null=True, blank=True, help_text="Average cost when sold.")
    discount_amount = MoneyField(default=0)
    order_discount_share = MoneyField(default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4)
    tax_name = models.CharField(max_length=60)
    tax_amount = MoneyField()
    line_total = MoneyField()

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["sale", "line_no"], name="sales_item_line_unique"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sales_item_qty_valid"),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0, discount_amount__gte=0, line_total__gte=0),
                name="sales_item_amounts_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(price_overridden=False) | ~models.Q(override_reason=""),
                name="sales_item_override_has_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.line_no}. {self.product_name}"
