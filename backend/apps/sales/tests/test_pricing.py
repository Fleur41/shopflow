"""The server pricing engine against the shared vectors (docs/PRICING.md)."""

import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from apps.sales.pricing import LineInput, PricingError, price_cart

# backend/apps/sales/tests → repository root. In Docker, /app/.. is /, so this
# resolves to the /shared mount.
VECTORS = Path(__file__).resolve().parents[4] / "shared" / "pricing-test-vectors" / "v1.json"
CASES: list[dict[str, Any]] = json.loads(VECTORS.read_text())["cases"]


def _price(given: dict[str, Any]) -> Any:
    return price_cart(
        [LineInput(**line) for line in given["lines"]],
        minor_units=given["minor_units"],
        tax_mode=given["tax_mode"],
        order_discount=given.get("order_discount", "0"),
    )


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_pricing_vectors(case):
    if "expected_error" in case:
        with pytest.raises(PricingError) as raised:
            _price(case["input"])
        assert {"code": raised.value.code, "line": raised.value.line} == case["expected_error"]
    else:
        assert dataclasses.asdict(_price(case["input"])) == case["expected"]


def test_totals_always_add_up_across_many_carts():
    """Invariants the vectors can't enumerate: discounts are fully allocated and
    each total is the sum of its lines, whatever the rounding."""
    prices = ["0.01", "0.99", "1.00", "33.3333", "80.00", "149.95", "1000"]
    quantities = ["1", "0.333", "2", "7.5"]
    rates = ["0", "0.08", "0.16"]
    for n in range(200):
        lines = [
            LineInput(
                quantity=quantities[(n + i) % len(quantities)],
                unit_price=prices[(n * 3 + i) % len(prices)],
                tax_rate=rates[(n + 2 * i) % len(rates)],
            )
            for i in range(1 + n % 5)
        ]
        for mode in ("INCLUSIVE", "EXCLUSIVE"):
            undiscounted = price_cart(lines, minor_units=2, tax_mode=mode)
            order_discount = str(min(Decimal(undiscounted.subtotal), (n % 13) * Decimal("0.37")))
            cart = price_cart(lines, minor_units=2, tax_mode=mode, order_discount=order_discount)

            def total(values: list[str]) -> Decimal:
                return sum((Decimal(v) for v in values), Decimal(0))

            assert total([line.order_discount for line in cart.lines]) == total([order_discount])
            assert total([line.line_total for line in cart.lines]) == total([cart.total])
            assert total([line.tax_amount for line in cart.lines]) == total([cart.tax_total])
            assert total([t.tax_amount for t in cart.taxes]) == total([cart.tax_total])
            if mode == "INCLUSIVE":
                assert total([cart.subtotal]) - total([cart.discount_total]) == total([cart.total])
