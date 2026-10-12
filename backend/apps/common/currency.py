"""Currency facts the money code needs."""

# ISO 4217 minor units for currencies that don't use 2 (East Africa first).
_MINOR_UNITS = {"UGX": 0, "RWF": 0, "BIF": 0, "JPY": 0, "KRW": 0, "BHD": 3, "KWD": 3}


def minor_units(currency: str) -> int:
    """Decimal places of the currency's smallest unit: KES 2, UGX 0."""
    return _MINOR_UNITS.get(currency, 2)
