"""Cash control: tills, their sessions and the cash moved in and out of them
(docs/ARCHITECTURE.md §6.8, docs/DATABASE.md §2.3a).

A session runs from opening (with a float) to a blind close-out count. While
it is open, cash sales, cash refunds and customer cash payments are linked to
it, and pay-ins, pay-outs and safe drops are recorded as append-only cash
movements. A closed session never changes (database trigger); a mistake found
later is a ``CORRECTION`` movement on it, which reports show separately.
"""

from typing import Any, ClassVar

from django.conf import settings
from django.db import models

from apps.audit.models import AppendOnlyError
from apps.common.fields import MoneyField
from apps.organizations.models import TenantManager, TenantModel

SESSION_STATUSES = ["OPEN", "CLOSED"]
MOVEMENT_TYPES = ["PAY_IN", "PAY_OUT", "DROP", "CORRECTION"]


class Till(TenantModel):
    """A cash drawer in a store. Phones get one each in Phase 6 (``device``)."""

    objects: ClassVar[TenantManager["Till"]]

    store = models.ForeignKey("organizations.Store", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["store", "name"], name="cash_till_name_unique"),
        ]

    def __str__(self) -> str:
        return self.name


class CashSession(TenantModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    objects: ClassVar[TenantManager["CashSession"]]

    store = models.ForeignKey("organizations.Store", on_delete=models.PROTECT, related_name="+")
    till = models.ForeignKey(Till, on_delete=models.PROTECT, related_name="sessions")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    client_txn_id = models.UUIDField()
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    opened_at = models.DateTimeField()
    opening_float = MoneyField()
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    expected_cash = MoneyField(null=True, blank=True)
    counted_cash = MoneyField(null=True, blank=True)
    variance = MoneyField(null=True, blank=True, help_text="Counted minus expected.")
    variance_reason = models.CharField(max_length=300, blank=True)
    denomination_count = models.JSONField(
        null=True, blank=True, help_text='e.g. {"1000": 3, "50": 4}: note or coin value → count.'
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["till"], condition=models.Q(status="OPEN"), name="cash_one_open_per_till"
            ),
            models.UniqueConstraint(
                fields=["organization", "client_txn_id"], name="cash_session_txn_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=SESSION_STATUSES), name="cash_session_status_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(opening_float__gte=0), name="cash_session_float_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(status="OPEN", closed_by__isnull=True, counted_cash__isnull=True)
                | models.Q(
                    status="CLOSED",
                    closed_by__isnull=False,
                    closed_at__isnull=False,
                    counted_cash__isnull=False,
                    expected_cash__isnull=False,
                    variance=models.F("counted_cash") - models.F("expected_cash"),
                ),
                name="cash_session_close_consistent",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["store", "opened_at"], name="cash_session_store_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.till} {self.opened_at:%Y-%m-%d %H:%M}"


class CashMovement(TenantModel):
    """Cash put in or taken out of the drawer for something other than a sale."""

    class Type(models.TextChoices):
        PAY_IN = "PAY_IN", "Pay in"
        PAY_OUT = "PAY_OUT", "Pay out"
        DROP = "DROP", "Safe drop"
        CORRECTION = "CORRECTION", "Correction"

    # The runtime database role gets no UPDATE/DELETE here (apps.common.db_grants).
    append_only = True
    objects: ClassVar[TenantManager["CashMovement"]]

    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=12, choices=Type.choices)
    amount = MoneyField(help_text="Positive. Corrections are signed: + found, - missing.")
    reason = models.CharField(max_length=300)
    client_txn_id = models.UUIDField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(movement_type__in=MOVEMENT_TYPES),
                name="cash_movement_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(movement_type="CORRECTION", amount__lt=0)
                | models.Q(amount__gt=0),
                name="cash_movement_amount_valid",
            ),
            models.CheckConstraint(condition=~models.Q(reason=""), name="cash_movement_has_reason"),
            models.UniqueConstraint(
                fields=["organization", "client_txn_id"], name="cash_movement_txn_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.movement_type} {self.amount}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Cash movements cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise AppendOnlyError("Cash movements cannot be deleted.")
