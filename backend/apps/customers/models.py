"""Customers and their credit accounts (docs/DATABASE.md §2.4).

A customer's balance is what they owe. It only changes through append-only
ledger entries, each numbered per account and carrying the balance after it,
so the balance can always be re-derived and checked (invariant 7). Balances
never go below zero: overpayments are refused (Q-6).
"""

from typing import Any, ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models

from apps.audit.models import AppendOnlyError
from apps.common.fields import CurrencyField, MoneyField
from apps.organizations.master_data import MasterData
from apps.organizations.models import TenantManager, TenantModel

ACCOUNT_STATUSES = ["ACTIVE", "FROZEN", "CLOSED"]
ENTRY_TYPES = ["OPENING_BALANCE", "CREDIT_SALE", "PAYMENT", "SALE_RETURN", "ADJUSTMENT", "REVERSAL"]


class Customer(MasterData):
    objects: ClassVar[TenantManager["Customer"]]
    audit_name = "customer"

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=16, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True, max_length=2000)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(OpClass("name", name="gin_trgm_ops"), name="customers_customer_name_trgm"),
            models.Index(fields=["organization", "phone"], name="customers_customer_phone_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class CustomerAccount(TenantModel):
    """What a customer owes in one currency, and how much credit they may have."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        FROZEN = "FROZEN", "Frozen: no new credit"
        CLOSED = "CLOSED", "Closed"

    objects: ClassVar[TenantManager["CustomerAccount"]]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="accounts")
    currency = CurrencyField()
    credit_limit = MoneyField(
        null=True, blank=True, help_text="Empty: no credit. 0 is also no credit."
    )
    balance = MoneyField(default=0, help_text="What the customer owes.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    last_entry_seq = models.BigIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["customer", "currency"], name="customers_account_currency_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(credit_limit__isnull=True) | models.Q(credit_limit__gte=0),
                name="customers_account_limit_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(balance__gte=0), name="customers_account_balance_not_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ACCOUNT_STATUSES),
                name="customers_account_status_valid",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["organization"],
                condition=models.Q(balance__gt=0),
                name="customers_account_owing_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.balance} {self.currency}"


class CustomerLedgerEntry(TenantModel):
    """One change to what a customer owes. Positive amounts add to the debt."""

    class Type(models.TextChoices):
        OPENING_BALANCE = "OPENING_BALANCE", "Opening balance"
        CREDIT_SALE = "CREDIT_SALE", "Credit sale"
        PAYMENT = "PAYMENT", "Payment"
        SALE_RETURN = "SALE_RETURN", "Return"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"
        REVERSAL = "REVERSAL", "Reversal"

    # The runtime database role gets no UPDATE/DELETE here (apps.common.db_grants).
    append_only = True
    objects: ClassVar[TenantManager["CustomerLedgerEntry"]]

    account = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name="+")
    store = models.ForeignKey(
        "organizations.Store", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    seq = models.BigIntegerField()
    entry_type = models.CharField(max_length=20, choices=Type.choices)
    amount = MoneyField()
    balance_after = MoneyField()
    description = models.CharField(max_length=300, blank=True)
    sale = models.ForeignKey(
        "sales.Sale", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    sale_return = models.ForeignKey(
        "sales.SaleReturn", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "customer ledger entries"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["account", "seq"], name="customers_entry_seq_unique"),
            models.CheckConstraint(
                condition=~models.Q(amount=0), name="customers_entry_amount_not_zero"
            ),
            models.CheckConstraint(
                condition=models.Q(balance_after__gte=0), name="customers_entry_balance_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(entry_type__in=ENTRY_TYPES), name="customers_entry_type_valid"
            ),
            # Each type points at its source document.
            models.CheckConstraint(
                condition=models.Q(entry_type="CREDIT_SALE", sale__isnull=False, amount__gt=0)
                | models.Q(entry_type="PAYMENT", payment__isnull=False, amount__lt=0)
                | models.Q(entry_type="REVERSAL", reverses__isnull=False)
                # A void (sale) or a return (sale_return) takes the credit back off.
                | models.Q(entry_type="SALE_RETURN", sale__isnull=False, amount__lt=0)
                | models.Q(entry_type="SALE_RETURN", sale_return__isnull=False, amount__lt=0)
                | models.Q(entry_type__in=["OPENING_BALANCE", "ADJUSTMENT"]),
                name="customers_entry_source",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["account", "occurred_at"], name="customers_entry_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.entry_type} {self.amount}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Ledger entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise AppendOnlyError("Ledger entries cannot be deleted.")
