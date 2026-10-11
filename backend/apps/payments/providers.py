"""Payment provider interface (docs/ARCHITECTURE.md §7).

A provider moves money for a payment method: ``MANUAL`` means the cashier
takes the money and, where required, types the reference (an M-Pesa code,
a card slip number). Integrations such as M-Pesa Daraja (STK push) or card
terminals implement the same interface later; payments then start
``PENDING`` and are confirmed asynchronously (Q-22).
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PaymentRequest:
    amount: Decimal
    currency: str
    reference: str = ""
    phone: str = ""  # for mobile-money push requests


@dataclass(frozen=True)
class PaymentOutcome:
    status: PaymentStatus
    reference: str = ""
    message: str = ""


class PaymentProvider(Protocol):
    label: str

    def initiate(self, request: PaymentRequest) -> PaymentOutcome:
        """Start taking a payment."""
        ...

    def confirm(self, reference: str) -> PaymentOutcome:
        """Check the outcome of a payment that started ``PENDING``."""
        ...

    def refund(self, reference: str, amount: Decimal) -> PaymentOutcome:
        """Return money for a confirmed payment."""
        ...


class ManualProvider:
    """The cashier handles the money; the payment is confirmed when recorded."""

    label = "Recorded by the cashier"

    def initiate(self, request: PaymentRequest) -> PaymentOutcome:
        return PaymentOutcome(PaymentStatus.CONFIRMED, reference=request.reference)

    def confirm(self, reference: str) -> PaymentOutcome:
        return PaymentOutcome(PaymentStatus.CONFIRMED, reference=reference)

    def refund(self, reference: str, amount: Decimal) -> PaymentOutcome:
        return PaymentOutcome(PaymentStatus.CONFIRMED, reference=reference)


PROVIDERS: dict[str, PaymentProvider] = {"MANUAL": ManualProvider()}


def get_provider(code: str) -> PaymentProvider:
    return PROVIDERS[code]
