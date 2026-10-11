"""Permission checks shared by views and services (docs/SECURITY.md §3)."""

from django.conf import settings

from .catalog import SENSITIVE_CODES
from .context import RequestContext
from .errors import MFAEnrollmentRequired, MissingPermission


def require_permission(ctx: RequestContext, code: str | None, *, method: str = "") -> None:
    """Raise unless the caller holds ``code``; sensitive codes also need two-step
    verification. ``None`` (nothing declared) always fails: fail closed."""
    if code is None or not ctx.has_perm(code):
        raise MissingPermission(
            "You don't have permission to do this. Ask the business owner for access.",
            errors=[
                {
                    "pointer": "",
                    "code": "MISSING_PERMISSION",
                    "meta": {"permission": code or f"undeclared:{method}"},
                }
            ],
        )
    if code in SENSITIVE_CODES and settings.MFA_ENFORCEMENT and not ctx.mfa_verified:
        raise MFAEnrollmentRequired(
            "Turn on two-step verification in your account settings to do this.",
            errors=[{"pointer": "", "code": "MFA_REQUIRED", "meta": {"permission": code}}],
        )
