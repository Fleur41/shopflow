"""How customers pay: an organization's payment methods (docs/DATABASE.md, Q-22).

Customer credit is not a payment method: it is ``sale.amount_on_credit``,
because no money moves.
"""

from typing import ClassVar

from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from apps.organizations.master_data import MasterData
from apps.organizations.models import TenantManager

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
