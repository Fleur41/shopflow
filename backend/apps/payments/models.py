"""How customers pay: an organization's payment methods (docs/DATABASE.md, Q-22).

Customer credit is not a payment method: it is ``sale.amount_on_credit``,
because no money moves.
"""

from typing import ClassVar

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from apps.common.fields import CurrencyField, MoneyField
from apps.organizations.master_data import MasterData
from apps.organizations.models import TenantManager, TenantModel

from .providers import PROVIDERS

PROVIDER_CHOICES = [(code, provider.label) for code, provider in PROVIDERS.items()]

payment_code_validator = RegexValidator(
    regex=r"^[A-Z0-9_]{2,20}$",
    message="Use 2-20 capital letters, digits or underscores, e.g. CASH or MPESA.",
)


class PaymentMethod(MasterData):
    class Kind(models.TextChoices):
        CASH = "CASH", "Cash"
        CARD = "CARD", "Card"
        MOBILE_MONEY = "MOBILE_MONEY", "Mobile money"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        OTHER = "OTHER", "Other"

    class EtimsPaymentType(models.TextChoices):
        """KRA eTIMS payment type codes (docs/ETIMS.md). ``02`` credit and
        ``03`` cash/credit describe a sale, not a payment method (Q-29)."""

        CASH = "01", "Cash"
        BANK_CHECK = "04", "Bank cheque"
        CARD = "05", "Debit or credit card"
        MOBILE_MONEY = "06", "Mobile money"
        OTHER = "07", "Other"

    objects: ClassVar[TenantManager["PaymentMethod"]]
    audit_name = "payment_method"
    unique_fields: ClassVar[dict[str, str]] = {
        "payments_method_code_unique": "code",
        "payments_method_name_unique": "name",
        "payments_method_one_cash": "kind",
    }

    code = models.CharField(
        max_length=20,
        validators=[payment_code_validator],
        help_text="Stable identifier used in reports and sync. Fixed once created.",
    )
    name = models.CharField(max_length=60)
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        help_text="Cash tenders give change and count towards the till. Fixed once created.",
    )
    provider = models.CharField(
        max_length=30,
        choices=PROVIDER_CHOICES,
        default="MANUAL",
    )
    requires_reference = models.BooleanField(
        default=False, help_text="The cashier must enter a reference, e.g. the M-Pesa code."
    )
    position = models.PositiveSmallIntegerField(
        default=0, help_text="Order of the tender buttons at the till."
    )
    etims_payment_type = models.CharField(
        max_length=2,
        choices=EtimsPaymentType.choices,
        help_text="How KRA eTIMS records this payment method.",
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "code"], name="payments_method_code_unique"
            ),
            models.UniqueConstraint(
                models.F("organization"), Lower("name"), name="payments_method_name_unique"
            ),
            # One cash drawer currency per store (Q-17), so one cash method.
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(kind="CASH"),
                name="payments_method_one_cash",
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[A-Z0-9_]{2,20}$"),
                name="payments_method_code_format",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=["CASH", "CARD", "MOBILE_MONEY", "BANK_TRANSFER", "OTHER"]
                ),
                name="payments_method_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(etims_payment_type__in=["01", "04", "05", "06", "07"]),
                name="payments_method_etims_type_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name


# eTIMS payment type when none is given.
DEFAULT_ETIMS_TYPES = {
    PaymentMethod.Kind.CASH: PaymentMethod.EtimsPaymentType.CASH,
    PaymentMethod.Kind.CARD: PaymentMethod.EtimsPaymentType.CARD,
    PaymentMethod.Kind.MOBILE_MONEY: PaymentMethod.EtimsPaymentType.MOBILE_MONEY,
    PaymentMethod.Kind.BANK_TRANSFER: PaymentMethod.EtimsPaymentType.OTHER,
    PaymentMethod.Kind.OTHER: PaymentMethod.EtimsPaymentType.OTHER,
}


class Payment(TenantModel):
    """Money that moved: a tender on a sale, or a customer paying their account.

    Never edited once confirmed; a refund is a new payment going ``OUT``. The
    same reference (an M-Pesa code) can't confirm two payments of one method,
    so a customer can't show the same M-Pesa message twice.
    """

    class Purpose(models.TextChoices):
        SALE = "SALE", "Sale"
        SALE_REFUND = "SALE_REFUND", "Sale refund"
        ACCOUNT_SETTLEMENT = "ACCOUNT_SETTLEMENT", "Customer account payment"
        SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT", "Supplier payment"

    class Direction(models.TextChoices):
        IN = "IN", "In"
        OUT = "OUT", "Out"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        FAILED = "FAILED", "Failed"
        REVERSED = "REVERSED", "Reversed"

    objects: ClassVar[TenantManager["Payment"]]

    store = models.ForeignKey("organizations.Store", on_delete=models.PROTECT, related_name="+")
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    direction = models.CharField(max_length=3, choices=Direction.choices, default=Direction.IN)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    amount = MoneyField()
    currency = CurrencyField()
    tendered = MoneyField(
        null=True, blank=True, help_text="Cash handed over; the change is tendered - amount."
    )
    external_reference = models.CharField(max_length=64, blank=True)
    position = models.PositiveSmallIntegerField(default=0, help_text="Order of tenders on a sale.")
    client_txn_id = models.UUIDField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)
    sale = models.ForeignKey(
        "sales.Sale", on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    sale_return = models.ForeignKey(
        "sales.SaleReturn", on_delete=models.PROTECT, null=True, blank=True, related_name="refunds"
    )
    cash_session = models.ForeignKey(
        "cash.CashSession",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="The till session cash went in or out of.",
    )
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payments_amount_valid"),
            models.CheckConstraint(
                condition=models.Q(tendered__isnull=True)
                | models.Q(tendered__gte=models.F("amount")),
                name="payments_tendered_covers_amount",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    purpose__in=["SALE", "SALE_REFUND", "ACCOUNT_SETTLEMENT", "SUPPLIER_PAYMENT"]
                ),
                name="payments_purpose_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["PENDING", "CONFIRMED", "FAILED", "REVERSED"]),
                name="payments_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    purpose="SALE", sale__isnull=False, customer_account__isnull=True
                )
                | models.Q(
                    purpose="ACCOUNT_SETTLEMENT", customer_account__isnull=False, sale__isnull=True
                )
                # A refund pays back a voided sale, or a return.
                | models.Q(purpose="SALE_REFUND", direction="OUT", sale__isnull=False)
                | models.Q(purpose="SALE_REFUND", direction="OUT", sale_return__isnull=False)
                | models.Q(purpose="SUPPLIER_PAYMENT"),
                name="payments_purpose_source",
            ),
            models.UniqueConstraint(
                fields=["organization", "client_txn_id"],
                condition=models.Q(client_txn_id__isnull=False),
                name="payments_txn_unique",
            ),
            models.UniqueConstraint(
                fields=["payment_method", "external_reference"],
                condition=~models.Q(external_reference="")
                & models.Q(direction="IN", status__in=["PENDING", "CONFIRMED"]),
                name="payments_reference_used_once",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["store", "occurred_at"], name="payments_store_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
