"""Cart pricing: line totals, discounts and tax (docs/PRICING.md).

The server's calculation is the authoritative one. The web and Android
clients implement the same steps for display, and every implementation must
pass ``shared/pricing-test-vectors/v1.json``. Arithmetic is on exact
integers scaled to a fixed number of decimal places, never floats.
"""

import re
from dataclasses import dataclass
from typing import Literal

TaxMode = Literal["INCLUSIVE", "EXCLUSIVE"]

QUANTITY_PLACES = 3
PRICE_PLACES = 4
RATE_PLACES = 4
MAX_MINOR_UNITS = 4

_PLAIN_DECIMAL = re.compile(r"^(\d+)(?:\.(\d+))?$")


class PricingError(ValueError):
    def __init__(self, code: str, line: int | None = None) -> None:
        super().__init__(code if line is None else f"{code} (line {line})")
        self.code = code
        self.line = line


@dataclass(frozen=True)
class LineInput:
    quantity: str
    unit_price: str
    tax_rate: str
    discount_amount: str = "0"


@dataclass(frozen=True)
class LinePrice:
    gross_amount: str
    discount_amount: str
    order_discount: str
    tax_amount: str
    line_total: str


@dataclass(frozen=True)
class TaxSummary:
    rate: str
    taxable_amount: str
    tax_amount: str


@dataclass(frozen=True)
class CartPrice:
    lines: list[LinePrice]
    subtotal: str
    discount_total: str
    tax_total: str
    total: str
    taxes: list[TaxSummary]


def price_cart(
    lines: list[LineInput],
    *,
    minor_units: int,
    tax_mode: str,
    order_discount: str = "0",
) -> CartPrice:
    if not 0 <= minor_units <= MAX_MINOR_UNITS or tax_mode not in ("INCLUSIVE", "EXCLUSIVE"):
        raise PricingError("INVALID_SETTINGS")
    minor = 10**minor_units
    rate_scale = 10**RATE_PLACES

    gross: list[int] = []  # all amounts in minor units
    discounts: list[int] = []
    rates: list[int] = []  # scaled by 10**RATE_PLACES
    for i, line in enumerate(lines):
        quantity = _parse(line.quantity, QUANTITY_PLACES, i)
        price = _parse(line.unit_price, PRICE_PLACES, i)
        discount = _parse(line.discount_amount, minor_units, i)
        rate = _parse(line.tax_rate, RATE_PLACES, i)
        if quantity == 0:
            raise PricingError("QUANTITY_NOT_POSITIVE", i)
        if rate >= rate_scale:
            raise PricingError("INVALID_TAX_RATE", i)
        line_gross = _round(quantity * price * minor, 10 ** (QUANTITY_PLACES + PRICE_PLACES))
        if discount > line_gross:
            raise PricingError("LINE_DISCOUNT_EXCEEDS_LINE", i)
        gross.append(line_gross)
        discounts.append(discount)
        rates.append(rate)

    net = [g - d for g, d in zip(gross, discounts, strict=True)]
    order = _parse(order_discount, minor_units, None)
    if order > sum(net):
        raise PricingError("ORDER_DISCOUNT_EXCEEDS_TOTAL")
    shares = _allocate(order, net)

    priced: list[LinePrice] = []
    taxes: dict[int, tuple[int, int]] = {}  # rate → (taxable, tax)
    tax_total = total = 0
    for i, rate in enumerate(rates):
        amount = net[i] - shares[i]
        if tax_mode == "INCLUSIVE":
            tax = _round(amount * rate, rate_scale + rate)
            line_total = amount
        else:
            tax = _round(amount * rate, rate_scale)
            line_total = amount + tax
        taxable, taxed = taxes.get(rate, (0, 0))
        taxes[rate] = (taxable + line_total - tax, taxed + tax)
        tax_total += tax
        total += line_total
        priced.append(
            LinePrice(
                gross_amount=_format(gross[i], minor_units),
                discount_amount=_format(discounts[i], minor_units),
                order_discount=_format(shares[i], minor_units),
                tax_amount=_format(tax, minor_units),
                line_total=_format(line_total, minor_units),
            )
        )

    return CartPrice(
        lines=priced,
        subtotal=_format(sum(gross), minor_units),
        discount_total=_format(sum(discounts) + order, minor_units),
        tax_total=_format(tax_total, minor_units),
        total=_format(total, minor_units),
        taxes=[
            TaxSummary(
                rate=_format(rate, RATE_PLACES),
                taxable_amount=_format(taxable, minor_units),
                tax_amount=_format(tax, minor_units),
            )
            for rate, (taxable, tax) in sorted(taxes.items())
        ],
    )


def _parse(value: str, places: int, line: int | None) -> int:
    """A plain decimal string as an integer scaled by ``10**places``."""
    match = _PLAIN_DECIMAL.match(value)
    if match is None:
        raise PricingError("INVALID_NUMBER", line)
    whole, fraction = match.group(1), match.group(2) or ""
    if len(fraction) > places:
        raise PricingError("TOO_MANY_DECIMALS", line)
    return int(whole + fraction.ljust(places, "0"))


def _round(numerator: int, denominator: int) -> int:
    """``numerator / denominator`` rounded half up (both non-negative)."""
    return (2 * numerator + denominator) // (2 * denominator)


def _allocate(amount: int, weights: list[int]) -> list[int]:
    """Split ``amount`` in proportion to ``weights`` by largest remainder;
    ties go to the earlier line."""
    total = sum(weights)
    if amount == 0 or total == 0:
        return [0] * len(weights)
    shares = [amount * w // total for w in weights]
    remainders = [amount * w % total for w in weights]
    by_remainder = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for i in by_remainder[: amount - sum(shares)]:
        shares[i] += 1
    return shares


def _format(value: int, places: int) -> str:
    if places == 0:
        return str(value)
    whole, fraction = divmod(value, 10**places)
    return f"{whole}.{fraction:0{places}d}"
