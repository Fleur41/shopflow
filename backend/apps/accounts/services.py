"""Authentication use cases: sign in, refresh, sign out, session revocation.

Views call these functions; they never touch sessions or tokens directly.
Security events are logged under the ``security`` logger (docs/SECURITY.md
§8). Email addresses are logged only as a short hash, never in clear text.
"""

import hashlib
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.common.errors import ApplicationError

from . import one_time_tokens
from .models import (
    AuthSession,
    OneTimeToken,
    RefreshToken,
    TOTPDevice,
    User,
    normalize_email_address,
)
from .tokens import generate_refresh_token, hash_refresh_token, issue_access_token

security_log = structlog.get_logger("security")


# --- Errors ------------------------------------------------------------------


class InvalidCredentials(ApplicationError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_CREDENTIALS"
    title = "Sign-in failed"


class LoginTemporarilyLocked(ApplicationError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "LOGIN_TEMPORARILY_LOCKED"
    title = "Too many failed sign-in attempts"


class RefreshTokenInvalid(ApplicationError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "SESSION_EXPIRED"
    title = "Session expired"


class RefreshInProgress(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    code = "REFRESH_IN_PROGRESS"
    title = "Session is being refreshed"


class MFARequired(ApplicationError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "MFA_REQUIRED"
    title = "Second step required"


class SessionNotFound(ApplicationError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    title = "Not found"


# --- Results -----------------------------------------------------------------


@dataclass(frozen=True)
class IssuedTokens:
    session: AuthSession
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


@dataclass(frozen=True)
class SessionState:
    """Cached view of a session used when authenticating every request."""

    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    active: bool
    mfa_verified: bool


# --- Sign in -----------------------------------------------------------------


def login(
    *,
    email: str,
    password: str,
    client_type: str,
    ip_address: str | None,
    user_agent: str,
    device_name: str = "",
    choose_organization: Callable[[User], uuid.UUID | None] | None = None,
) -> IssuedTokens:
    """Verify credentials and open a new session.

    ``choose_organization`` picks the business the session works in once the
    user is known (the tenancy layer supplies it; it may raise to refuse).

    Unknown emails, wrong passwords and inactive accounts all produce the same
    error, and lockout applies to unknown emails too, so responses never
    reveal whether an account exists. Django's ``authenticate`` also runs the
    password hasher for unknown users to equalise timing.
    """
    normalized = normalize_email_address(email)
    retry_after = _lockout_remaining(normalized)
    if retry_after:
        raise _locked_error(retry_after)

    user = authenticate(username=normalized, password=password)
    if not isinstance(user, User):
        _register_failure(normalized, ip_address)
        raise InvalidCredentials("The email or password is incorrect.")

    reset_login_failures(normalized)
    organization_id = choose_organization(user) if choose_organization else None
    if TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).exists():
        challenge = one_time_tokens.issue(
            user,
            OneTimeToken.Purpose.MFA_CHALLENGE,
            settings.AUTH_MFA_CHALLENGE_LIFETIME,
            payload={
                "client_type": client_type,
                "organization_id": str(organization_id) if organization_id else None,
                "ip_address": ip_address,
                "user_agent": user_agent[:256],
                "device_name": device_name[:100],
            },
        )
        security_log.info("auth.mfa_challenge_issued", user_id=str(user.pk), ip=ip_address)
        raise MFARequired(
            "Enter the 6-digit code from your authenticator app.", extra={"mfa_token": challenge}
        )
    with transaction.atomic():
        issued = start_session(
            user=user,
            client_type=client_type,
            organization_id=organization_id,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
        )
        update_last_login(sender=User, user=user)
        session = issued.session

    security_log.info(
        "auth.login_succeeded",
        user_id=str(user.pk),
        session_id=str(session.pk),
        client_type=client_type,
        ip=ip_address,
    )
    return issued


def start_session(
    *,
    user: User,
    client_type: str,
    organization_id: uuid.UUID | None,
    ip_address: str | None,
    user_agent: str,
    device_name: str = "",
    mfa_verified: bool = False,
) -> IssuedTokens:
    """Open a session for an already-authenticated user (sign-in, sign-up, switch)."""
    now = timezone.now()
    session = AuthSession.objects.create(
        user=user,
        organization_id=organization_id,
        mfa_verified=mfa_verified,
        client_type=client_type,
        device_name=device_name[:100],
        user_agent=user_agent[:256],
        ip_address=ip_address,
        last_used_at=now,
        expires_at=now + _session_max_lifetime(client_type),
    )
    return _issue_tokens(session, now=now)


def switch_organization(*, session_id: uuid.UUID, organization_id: uuid.UUID) -> IssuedTokens:
    """Replace the current session with a new one bound to another business.

    The caller must already have verified the user's membership. The old
    session is revoked so each session only ever acts for one business.
    """
    with transaction.atomic():
        current = (
            AuthSession.objects.select_for_update()
            .select_related("user")
            .get(pk=session_id, revoked_at__isnull=True)
        )
        _revoke(current, AuthSession.RevokeReason.SWITCHED_ORGANIZATION, now=timezone.now())
        return start_session(
            user=current.user,
            client_type=current.client_type,
            organization_id=organization_id,
            ip_address=current.ip_address,
            user_agent=current.user_agent,
            device_name=current.device_name,
            mfa_verified=current.mfa_verified,
        )


def revoke_organization_sessions(*, user_id: uuid.UUID, organization_id: uuid.UUID) -> int:
    """End a user's sessions for one business (e.g. their membership was suspended)."""
    with transaction.atomic():
        now = timezone.now()
        sessions = list(
            AuthSession.objects.select_for_update().filter(
                user_id=user_id, organization_id=organization_id, revoked_at__isnull=True
            )
        )
        for session in sessions:
            _revoke(session, AuthSession.RevokeReason.MEMBERSHIP_SUSPENDED, now=now)
    return len(sessions)


# --- Refresh -----------------------------------------------------------------


def refresh(*, refresh_token: str, client_type: str) -> IssuedTokens:
    """Rotate a refresh token: retire the presented one and issue a new pair.

    Reuse of an already-rotated token outside the grace window revokes the
    whole session, because it means the token was copied.
    """
    token_hash = hash_refresh_token(refresh_token)
    reuse_detected = False
    with transaction.atomic():
        token = (
            RefreshToken.objects.select_for_update()
            .select_related("session__user")
            .filter(token_hash=token_hash)
            .first()
        )
        if token is None or token.session.client_type != client_type:
            raise RefreshTokenInvalid("Your session has expired. Please sign in again.")

        session = token.session
        now = timezone.now()
        if token.rotated_at is not None:
            if now - token.rotated_at <= settings.AUTH_REFRESH_REUSE_GRACE:
                raise RefreshInProgress("The session was just refreshed. Retry the request.")
            if session.revoked_at is None:
                _revoke(session, AuthSession.RevokeReason.TOKEN_REUSE, now=now)
                reuse_detected = True
        elif _is_usable(session, token, now):
            token.rotated_at = now
            token.save(update_fields=["rotated_at", "updated_at"])
            session.last_used_at = now
            session.save(update_fields=["last_used_at", "updated_at"])
            return _issue_tokens(session, now=now)

    # Reached only on failure, after the transaction (and any revocation) committed.
    if reuse_detected:
        security_log.warning(
            "auth.refresh_token_reuse_detected",
            user_id=str(session.user_id),
            session_id=str(session.pk),
        )
    raise RefreshTokenInvalid("Your session has expired. Please sign in again.")


def _is_usable(session: AuthSession, token: RefreshToken, now: datetime) -> bool:
    return (
        session.revoked_at is None
        and session.expires_at > now
        and token.expires_at > now
        and session.user.is_active
    )


# --- Sign out and session management -----------------------------------------


def logout(*, session_id: uuid.UUID) -> None:
    with transaction.atomic():
        session = AuthSession.objects.select_for_update().filter(pk=session_id).first()
        if session is not None and session.revoked_at is None:
            _revoke(session, AuthSession.RevokeReason.LOGOUT, now=timezone.now())


def logout_all(*, user: User) -> int:
    """Revoke every active session of ``user``. Returns how many were revoked."""
    with transaction.atomic():
        now = timezone.now()
        sessions = list(
            AuthSession.objects.select_for_update().filter(user=user, revoked_at__isnull=True)
        )
        for session in sessions:
            _revoke(session, AuthSession.RevokeReason.LOGOUT_ALL, now=now)
    security_log.info("auth.logout_all", user_id=str(user.pk), sessions=len(sessions))
    return len(sessions)


def revoke_user_session(*, user: User, session_id: uuid.UUID) -> None:
    """Revoke one of the user's own sessions. Other users' sessions are 'not found'."""
    with transaction.atomic():
        session = (
            AuthSession.objects.select_for_update()
            .filter(pk=session_id, user=user, revoked_at__isnull=True)
            .first()
        )
        if session is None:
            raise SessionNotFound("Session not found.")
        _revoke(session, AuthSession.RevokeReason.REVOKED_BY_USER, now=timezone.now())


def get_session_state(session_id: uuid.UUID) -> SessionState | None:
    """Return whether a session may be used, consulting the cache first."""
    key = _session_cache_key(session_id)
    cached = cache.get(key)
    if isinstance(cached, SessionState):
        return cached

    row = (
        AuthSession.objects.filter(pk=session_id)
        .values_list("user_id", "organization_id", "revoked_at", "expires_at", "mfa_verified")
        .first()
    )
    if row is None:
        return None
    user_id, organization_id, revoked_at, expires_at, mfa_verified = row
    now = timezone.now()
    state = SessionState(
        user_id=user_id,
        organization_id=organization_id,
        active=revoked_at is None and expires_at > now,
        mfa_verified=mfa_verified,
    )
    # Never cache an active session beyond its own expiry.
    ttl = settings.AUTH_SESSION_CACHE_SECONDS
    if state.active:
        ttl = min(ttl, max(1, int((expires_at - now).total_seconds())))
    cache.set(key, state, timeout=ttl)
    return state


# --- Internals ---------------------------------------------------------------


def _issue_tokens(session: AuthSession, *, now: datetime) -> IssuedTokens:
    raw_refresh = generate_refresh_token()
    refresh_expires_at = min(now + _refresh_idle_lifetime(session.client_type), session.expires_at)
    RefreshToken.objects.create(
        session=session,
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=refresh_expires_at,
    )
    access_token, access_expires_at = issue_access_token(
        user_id=session.user_id, session_id=session.pk
    )
    return IssuedTokens(
        session=session,
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=raw_refresh,
        refresh_expires_at=refresh_expires_at,
    )


def forget_session_state(session_id: uuid.UUID) -> None:
    """Drop the cached state now and after commit (after changing a session row)."""
    key = _session_cache_key(session_id)
    cache.delete(key)
    transaction.on_commit(lambda: cache.delete(key))


def revoke_sessions(*, user: User, reason: str, keep_session_id: uuid.UUID | None = None) -> int:
    """End a user's sessions (optionally keeping the current one)."""
    with transaction.atomic():
        now = timezone.now()
        sessions = AuthSession.objects.select_for_update().filter(
            user=user, revoked_at__isnull=True
        )
        if keep_session_id is not None:
            sessions = sessions.exclude(pk=keep_session_id)
        ended = list(sessions)
        for session in ended:
            _revoke(session, reason, now=now)
    return len(ended)


def _revoke(session: AuthSession, reason: str, *, now: datetime) -> None:
    session.revoked_at = now
    session.revoke_reason = reason
    session.save(update_fields=["revoked_at", "revoke_reason", "updated_at"])
    # Drop the cached state now and again after commit, so access tokens for
    # this session stop working on the very next request, even if a concurrent
    # request re-cached the old state before the revocation committed.
    key = _session_cache_key(session.pk)
    cache.delete(key)
    transaction.on_commit(lambda: cache.delete(key))


def _session_cache_key(session_id: uuid.UUID) -> str:
    # Versioned: bump when SessionState's shape changes so stale pickles are ignored.
    return f"auth:session:v3:{session_id}"


def _session_max_lifetime(client_type: str) -> timedelta:
    if client_type == AuthSession.ClientType.MOBILE:
        return settings.AUTH_MOBILE_SESSION_MAX_LIFETIME
    return settings.AUTH_WEB_SESSION_MAX_LIFETIME


def _refresh_idle_lifetime(client_type: str) -> timedelta:
    if client_type == AuthSession.ClientType.MOBILE:
        return settings.AUTH_MOBILE_REFRESH_IDLE_LIFETIME
    return settings.AUTH_WEB_REFRESH_IDLE_LIFETIME


# --- Lockout (per email address, including unknown ones) ----------------------


def email_fingerprint(normalized_email: str) -> str:
    """Short, non-reversible identifier for logs and cache keys."""
    return hashlib.sha256(normalized_email.encode()).hexdigest()[:16]


def _failures_key(normalized_email: str) -> str:
    return f"auth:login_failures:{email_fingerprint(normalized_email)}"


def _lock_key(normalized_email: str) -> str:
    return f"auth:login_locked:{email_fingerprint(normalized_email)}"


def _lockout_remaining(normalized_email: str) -> int:
    locked_until = cache.get(_lock_key(normalized_email))
    if not isinstance(locked_until, float):
        return 0
    return max(0, math.ceil(locked_until - timezone.now().timestamp()))


def _register_failure(normalized_email: str, ip_address: str | None) -> None:
    window = int(settings.AUTH_LOCKOUT_WINDOW.total_seconds())
    key = _failures_key(normalized_email)
    cache.add(key, 0, timeout=window)
    try:
        failures = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=window)
        failures = 1

    fingerprint = email_fingerprint(normalized_email)
    security_log.info("auth.login_failed", email_fp=fingerprint, ip=ip_address, failures=failures)
    if failures >= settings.AUTH_LOCKOUT_THRESHOLD:
        duration = settings.AUTH_LOCKOUT_DURATION.total_seconds()
        cache.set(
            _lock_key(normalized_email),
            timezone.now().timestamp() + duration,
            timeout=int(duration),
        )
        cache.delete(key)
        security_log.warning("auth.login_locked", email_fp=fingerprint, ip=ip_address)


def reset_login_failures(normalized_email: str) -> None:
    cache.delete(_failures_key(normalized_email))


def unlock_login(normalized_email: str) -> None:
    """Clear both the failure count and any active lock (e.g. after a password reset)."""
    cache.delete_many([_failures_key(normalized_email), _lock_key(normalized_email)])


def _locked_error(retry_after: int) -> LoginTemporarilyLocked:
    minutes = max(1, (retry_after + 59) // 60)
    return LoginTemporarilyLocked(
        f"Too many failed sign-in attempts. Try again in {minutes} minute"
        f"{'s' if minutes != 1 else ''}.",
        headers={"Retry-After": str(retry_after)},
    )
