"""Identifier generation.

Primary keys are UUIDv7 (RFC 9562): the leading 48 bits are a Unix
millisecond timestamp, so new rows land at the end of B-tree indexes and IDs
sort roughly by creation time, while remaining unguessable.
"""

import os
import time
import uuid

_TIMESTAMP_MASK = (1 << 48) - 1
_RAND_A_MASK = (1 << 12) - 1
_RAND_B_MASK = (1 << 62) - 1


def uuid7() -> uuid.UUID:
    """Return a new random UUIDv7."""
    timestamp_ms = time.time_ns() // 1_000_000
    random_bits = int.from_bytes(os.urandom(10), "big")
    rand_a = (random_bits >> 62) & _RAND_A_MASK
    rand_b = random_bits & _RAND_B_MASK
    value = (
        (timestamp_ms & _TIMESTAMP_MASK) << 80
        | 0x7 << 76  # version
        | rand_a << 64
        | 0b10 << 62  # RFC 9562 variant
        | rand_b
    )
    return uuid.UUID(int=value)
