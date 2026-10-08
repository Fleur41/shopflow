"""TOTP (RFC 6238) secrets, codes and recovery codes.

* Secrets are encrypted at rest (Fernet, keys from MFA_ENCRYPTION_KEYS;
  the first key encrypts, all keys decrypt so keys can be rotated).
* Codes are accepted for the current 30-second step and one step either
  side (clock drift), and never twice: the accepted step is remembered.
* Recovery codes are random, shown once, stored as SHA-256 hashes.
"""

import hashlib
import hmac
import secrets
import time

import pyotp
import segno
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings

STEP_SECONDS = 30
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10


def _cipher() -> MultiFernet:
    return MultiFernet([Fernet(key.encode()) for key in settings.MFA_ENCRYPTION_KEYS])


def encrypt_secret(secret: str) -> str:
    return _cipher().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _cipher().decrypt(token.encode()).decode()


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=settings.MFA_ISSUER)


def qr_data_uri(uri: str) -> str:
    """PNG QR code as a data: URI (allowed by the CSP's img-src)."""
    return str(segno.make(uri, error="m").png_data_uri(scale=5, border=2))


def matching_step(secret: str, code: str, *, after_step: int | None) -> int | None:
    """Return the time step ``code`` is valid for, if any and newer than ``after_step``."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    current = int(time.time()) // STEP_SECONDS
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if after_step is not None and step <= after_step:
            continue  # already used (or older): replay
        if hmac.compare_digest(totp.at(step * STEP_SECONDS), code):
            return step
    return None


def new_recovery_codes() -> list[str]:
    """Human-friendly codes like ``k7m2-9xqp-4tzr``."""
    alphabet = "23456789abcdefghjkmnpqrstuvwxyz"  # no 0/o/1/l/i
    return [
        "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def hash_recovery_code(code: str) -> str:
    normalized = code.strip().lower().replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()
