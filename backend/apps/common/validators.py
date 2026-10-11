"""Small validators shared across apps."""

import re

from django.core.exceptions import ValidationError

_PHONE = re.compile(r"^\+?[0-9]{7,15}$")
_KRA_PIN = re.compile(r"^[AP][0-9]{9}[A-Z]$")


def normalize_phone(value: str) -> str:
    """Accept common ways of writing a number ("+254 712 345-678", "(020) 444 5555")
    and keep digits with an optional leading "+". Empty stays empty."""
    value = value.strip()
    if not value:
        return ""
    compact = re.sub(r"[\s().-]", "", value)
    if not _PHONE.match(compact):
        raise ValidationError("Enter a phone number with 7 to 15 digits, e.g. +254712345678.")
    return compact


def normalize_kra_pin(value: str) -> str:
    """A Kenya Revenue Authority PIN: P051234567X (businesses) or A123456789B (individuals)."""
    value = value.strip().upper()
    if value and not _KRA_PIN.match(value):
        raise ValidationError("A KRA PIN is a letter, 9 digits and a letter, e.g. P051234567X.")
    return value
