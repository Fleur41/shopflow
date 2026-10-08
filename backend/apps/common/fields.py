"""Model fields for money, quantities and currencies.

Money and quantities are fixed-point decimals, never floats
(docs/ARCHITECTURE.md, ADR-05). Use these fields instead of declaring
DecimalField precision ad hoc so every table agrees.
"""

from typing import Any

from django.core.validators import RegexValidator
from django.db import models

MONEY_MAX_DIGITS = 19
MONEY_DECIMAL_PLACES = 4
QUANTITY_MAX_DIGITS = 14
QUANTITY_DECIMAL_PLACES = 3

currency_code_validator = RegexValidator(
    regex=r"^[A-Z]{3}$", message="Enter a three-letter ISO 4217 currency code."
)


class MoneyField(models.DecimalField):  # type: ignore[type-arg]
    """An amount of money; always pair it with a currency on the owning record."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", MONEY_MAX_DIGITS)
        kwargs.setdefault("decimal_places", MONEY_DECIMAL_PLACES)
        super().__init__(*args, **kwargs)


class QuantityField(models.DecimalField):  # type: ignore[type-arg]
    """A stock quantity. Whether fractions are allowed is a unit-of-measure rule."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", QUANTITY_MAX_DIGITS)
        kwargs.setdefault("decimal_places", QUANTITY_DECIMAL_PLACES)
        super().__init__(*args, **kwargs)


class CurrencyField(models.CharField):  # type: ignore[type-arg]
    """An ISO 4217 currency code such as ``KES``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 3)
        kwargs.setdefault("validators", [currency_code_validator])
        super().__init__(*args, **kwargs)
