"""Account lifecycle: email verification, password reset/change, two-step verification.

Security events are logged (``security`` logger) and, where the account
holder should know, emailed. Responses never reveal whether an email address
has an account.
"""

import uuid
from dataclasses import dataclass

import structlog
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status

from apps.common.errors import ApplicationError

from . import mfa, one_time_tokens
from .emails import link, send_templated_email
from .models import (
    AuthSession,
    OneTimeToken,
    RecoveryCode,
    TOTPDevice,
    User,
    normalize_email_address,
)
from .services import (
    IssuedTokens,
    forget_session_state,
    revoke_sessions,
    start_session,
    unlock_login,
)

security_log = structlog.get_logger("security")


class MFACodeInvalid(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "MFA_CODE_INVALID"
    title = "Code not accepted"


class MFAAlreadyEnabled(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    code = "MFA_ALREADY_ENABLED"
    title = "Two-step verification is already on"


class MFANotEnabled(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    code = "MFA_NOT_ENABLED"
    title = "Two-step verification is off"


def _validate_new_password(password: str, user: User, field: str = "new_password") -> None:
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({field: list(exc.messages)}) from exc


def _notify(user: User, event: str) -> None:
    send_templated_email(
        to=user.email,
        template="security_notice",
        context={
            "name": user.full_name,
            "event": event,
            "reset_url": f"{settings.FRONTEND_URL}/forgot-password",
        },
    )


# --- Email verification -------------------------------------------------------


def send_email_verification(user: User) -> None:
    if user.email_verified_at is not None:
        return
    raw = one_time_tokens.issue(
        user, OneTimeToken.Purpose.VERIFY_EMAIL, settings.AUTH_EMAIL_VERIFICATION_LIFETIME
    )
    send_templated_email(
        to=user.email,
        template="verify_email",
        context={"name": user.full_name, "url": link("/verify-email", raw)},
    )


def verify_email(raw: str) -> User:
    with transaction.atomic():
        token = one_time_tokens.lock_open(raw, OneTimeToken.Purpose.VERIFY_EMAIL)
        one_time_tokens.mark_used(token)
        user = token.user
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
    security_log.info("auth.email_verified", user_id=str(user.pk))
    return user


# --- Passwords --------------------------------------------------------------------


def request_password_reset(email: str) -> None:
    """Email a reset link if the account exists. Always looks the same to the caller."""
    user = User.objects.filter(email=normalize_email_address(email), is_active=True).first()
    if user is None:
        return
    raw = one_time_tokens.issue(
        user, OneTimeToken.Purpose.RESET_PASSWORD, settings.AUTH_PASSWORD_RESET_LIFETIME
    )
    send_templated_email(
        to=user.email,
        template="password_reset",
        context={"name": user.full_name, "url": link("/reset-password", raw)},
    )
    security_log.info("auth.password_reset_requested", user_id=str(user.pk))


def confirm_password_reset(raw: str, new_password: str) -> User:
    """Set a new password from a reset link. Every session ends; sign in again."""
    with transaction.atomic():
        token = one_time_tokens.lock_open(raw, OneTimeToken.Purpose.RESET_PASSWORD)
        user = token.user
        _validate_new_password(new_password, user)
        one_time_tokens.mark_used(token)
        user.set_password(new_password)
        user.save(update_fields=["password"])
        revoke_sessions(user=user, reason=AuthSession.RevokeReason.PASSWORD_CHANGED)
    unlock_login(user.email)  # a locked-out owner can get back in
    _notify(user, "Your password was reset")
    security_log.info("auth.password_reset_completed", user_id=str(user.pk))
    return user


def change_password(
    user: User, *, session_id: uuid.UUID, current_password: str, new_password: str
) -> None:
    """Change password while signed in. Other sessions end; this one continues."""
    if not user.check_password(current_password):
        raise serializers.ValidationError(
            {"current_password": ["Your current password is incorrect."]}
        )
    _validate_new_password(new_password, user)
    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        revoke_sessions(
            user=user, reason=AuthSession.RevokeReason.PASSWORD_CHANGED, keep_session_id=session_id
        )
    _notify(user, "Your password was changed")
    security_log.info("auth.password_changed", user_id=str(user.pk))


# --- Two-step verification ------------------------------------------------------------


@dataclass(frozen=True)
class TOTPSetup:
    secret: str
    otpauth_uri: str
    qr_code: str  # PNG data: URI


def begin_totp_setup(user: User) -> TOTPSetup:
    """Start (or restart) enrolment. Nothing changes for sign-in until confirmed."""
    secret = mfa.new_secret()
    with transaction.atomic():
        device = TOTPDevice.objects.select_for_update().filter(user=user).first()
        if device is not None and device.confirmed_at is not None:
            raise MFAAlreadyEnabled("Turn off two-step verification before setting it up again.")
        TOTPDevice.objects.update_or_create(
            user=user,
            defaults={
                "secret_encrypted": mfa.encrypt_secret(secret),
                "confirmed_at": None,
                "last_used_counter": None,
            },
        )
    uri = mfa.provisioning_uri(secret, user.email)
    return TOTPSetup(secret=secret, otpauth_uri=uri, qr_code=mfa.qr_data_uri(uri))


def confirm_totp(user: User, *, session_id: uuid.UUID, code: str) -> list[str]:
    """Finish enrolment with a first code. Returns recovery codes (shown once).

    This session becomes MFA-verified and every other session ends, so anyone
    who signed in with a stolen password before enrolment is locked out.
    """
    with transaction.atomic():
        device = TOTPDevice.objects.select_for_update().filter(user=user).first()
        if device is None:
            raise MFANotEnabled("Start two-step verification setup first.")
        if device.confirmed_at is not None:
            raise MFAAlreadyEnabled("Two-step verification is already on.")
        step = mfa.matching_step(mfa.decrypt_secret(device.secret_encrypted), code, after_step=None)
        if step is None:
            raise MFACodeInvalid("That code didn't match. Check your phone's time and try again.")
        device.confirmed_at = timezone.now()
        device.last_used_counter = step
        device.save(update_fields=["confirmed_at", "last_used_counter", "updated_at"])
        codes = _replace_recovery_codes(user)
        AuthSession.objects.filter(pk=session_id, user=user).update(mfa_verified=True)
        forget_session_state(session_id)
        revoke_sessions(
            user=user, reason=AuthSession.RevokeReason.MFA_ENABLED, keep_session_id=session_id
        )
    _notify(user, "Two-step verification was turned on")
    security_log.info("auth.mfa_enabled", user_id=str(user.pk))
    return codes


def disable_totp(user: User, *, session_id: uuid.UUID, password: str, code: str) -> None:
    """Turn MFA off; needs the password and a current code (or a recovery code)."""
    if not user.check_password(password):
        raise serializers.ValidationError({"password": ["Your password is incorrect."]})
    with transaction.atomic():
        device = TOTPDevice.objects.select_for_update().filter(user=user).first()
        if device is None or device.confirmed_at is None:
            raise MFANotEnabled("Two-step verification is not on.")
        if not _accept_second_factor(user, device, code):
            raise MFACodeInvalid("That code didn't match.")
        device.delete()
        RecoveryCode.objects.filter(user=user).delete()
        AuthSession.objects.filter(user=user, revoked_at__isnull=True).update(mfa_verified=False)
        forget_session_state(session_id)
        revoke_sessions(
            user=user, reason=AuthSession.RevokeReason.MFA_DISABLED, keep_session_id=session_id
        )
    _notify(user, "Two-step verification was turned off")
    security_log.warning("auth.mfa_disabled", user_id=str(user.pk))


def complete_mfa_login(raw_challenge: str, code: str) -> IssuedTokens:
    """Second sign-in step: a TOTP code or a recovery code completes the session."""
    failed = False
    with transaction.atomic():
        token = one_time_tokens.lock_open(raw_challenge, OneTimeToken.Purpose.MFA_CHALLENGE)
        if token.attempts >= settings.AUTH_MFA_MAX_ATTEMPTS:
            raise one_time_tokens.TokenInvalid("Too many attempts. Sign in again.")
        user = token.user
        device = TOTPDevice.objects.select_for_update().filter(user=user).first()
        if (
            device is not None
            and device.confirmed_at is not None
            and _accept_second_factor(user, device, code)
        ):
            one_time_tokens.mark_used(token)
            payload = token.payload
            organization_id = payload.get("organization_id")
            issued = start_session(
                user=user,
                client_type=payload["client_type"],
                organization_id=uuid.UUID(organization_id) if organization_id else None,
                ip_address=payload.get("ip_address"),
                user_agent=payload.get("user_agent", ""),
                device_name=payload.get("device_name", ""),
                mfa_verified=True,
            )
        else:
            token.attempts += 1
            token.save(update_fields=["attempts", "updated_at"])
            failed = True
    if failed:  # outside the transaction so the attempt count is kept
        security_log.info("auth.mfa_failed", user_id=str(user.pk), attempts=token.attempts)
        raise MFACodeInvalid("That code didn't match. Try again.")
    security_log.info("auth.login_succeeded", user_id=str(user.pk), mfa=True)
    return issued


def _accept_second_factor(user: User, device: TOTPDevice, code: str) -> bool:
    """Accept a fresh TOTP code (never one already used) or an unused recovery code."""
    step = mfa.matching_step(
        mfa.decrypt_secret(device.secret_encrypted), code, after_step=device.last_used_counter
    )
    if step is not None:
        device.last_used_counter = step
        device.save(update_fields=["last_used_counter", "updated_at"])
        return True
    recovery = (
        RecoveryCode.objects.select_for_update()
        .filter(user=user, code_hash=mfa.hash_recovery_code(code), used_at__isnull=True)
        .first()
    )
    if recovery is not None:
        recovery.used_at = timezone.now()
        recovery.save(update_fields=["used_at", "updated_at"])
        security_log.warning("auth.recovery_code_used", user_id=str(user.pk))
        return True
    return False


def _replace_recovery_codes(user: User) -> list[str]:
    codes = mfa.new_recovery_codes()
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create(
        RecoveryCode(user=user, code_hash=mfa.hash_recovery_code(c)) for c in codes
    )
    return codes
