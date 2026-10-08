import time
import uuid

import pytest
from django.core.exceptions import ValidationError

from apps.common.fields import CurrencyField, MoneyField, QuantityField
from apps.common.ids import uuid7


def test_uuid7_has_version_and_variant():
    value = uuid7()

    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_embeds_current_millisecond_timestamp():
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000

    assert before <= value.int >> 80 <= after


def test_uuid7_sorts_by_creation_time_across_milliseconds():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()

    assert first < second


def test_uuid7_is_unique():
    assert len({uuid7() for _ in range(10_000)}) == 10_000


def test_money_and_quantity_precision():
    money = MoneyField()
    quantity = QuantityField()

    assert (money.max_digits, money.decimal_places) == (19, 4)
    assert (quantity.max_digits, quantity.decimal_places) == (14, 3)


@pytest.mark.parametrize("code", ["KES", "USD"])
def test_currency_field_accepts_iso_codes(code):
    CurrencyField().run_validators(code)


@pytest.mark.parametrize("code", ["kes", "KE", "KESS", "1ES"])
def test_currency_field_rejects_invalid_codes(code):
    with pytest.raises(ValidationError):
        CurrencyField().run_validators(code)
