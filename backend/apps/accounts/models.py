from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.common.ids import uuid7
from apps.common.models import BaseModel


def normalize_email_address(email: str) -> str:
    """Emails are stored trimmed and lower-case, so lookups and uniqueness are exact."""
    return email.strip().lower()


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> "User":
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> "User":
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, username: str | None) -> "User":
        return self.get(email=normalize_email_address(username or ""))

    def _create_user(self, email: str, password: str | None, **extra: Any) -> "User":
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=normalize_email_address(email), **extra)
        user.set_password(password)  # None → unusable password (e.g. invited users)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """A person who can sign in.

    Business access (organizations, stores, roles) lives in memberships, not
    here. ``is_staff``/``is_superuser`` and the Django permission tables are
    used only for the internal platform admin site, never for shop
    authorization (docs/SECURITY.md §3).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = ["full_name"]

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="accounts_user_email_lowercase",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        super().clean()
        self.email = normalize_email_address(self.email)


class AuthSession(BaseModel):
    """One signed-in client (a browser or a mobile device).

    Every access token names its session (``sid``), so revoking a session
    invalidates its access tokens immediately, not when they expire. A
    session's refresh tokens form a rotation chain (:class:`RefreshToken`).
    """

    class ClientType(models.TextChoices):
        WEB = "WEB", "Web browser"
        MOBILE = "MOBILE", "Mobile app"

    class RevokeReason(models.TextChoices):
        LOGOUT = "LOGOUT", "Signed out"
        LOGOUT_ALL = "LOGOUT_ALL", "Signed out everywhere"
        REVOKED_BY_USER = "REVOKED_BY_USER", "Revoked from session list"
        TOKEN_REUSE = "TOKEN_REUSE", "Refresh token reuse detected"
        PASSWORD_CHANGED = "PASSWORD_CHANGED", "Password changed"
        ADMIN = "ADMIN", "Revoked by an administrator"
        SWITCHED_ORGANIZATION = "SWITCHED_ORGANIZATION", "Switched to another business"
        MEMBERSHIP_SUSPENDED = "MEMBERSHIP_SUSPENDED", "Access to the business was suspended"
        MFA_ENABLED = "MFA_ENABLED", "Two-step verification was turned on"
        MFA_DISABLED = "MFA_DISABLED", "Two-step verification was turned off"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="auth_sessions")
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="The business this session works in. Null until one is chosen.",
    )
    mfa_verified = models.BooleanField(
        default=False,
        help_text="Signed in with a second factor (or enrolled during this session).",
    )
    client_type = models.CharField(max_length=10, choices=ClientType.choices)
    device_name = models.CharField(max_length=100, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_used_at = models.DateTimeField()
    expires_at = models.DateTimeField(help_text="Absolute end of the session.")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=24, choices=RevokeReason.choices, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["user"],
                condition=models.Q(revoked_at__isnull=True),
                name="accounts_session_active_user",
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(client_type__in=["WEB", "MOBILE"]),
                name="accounts_session_client_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__isnull=True, revoke_reason="")
                    | (models.Q(revoked_at__isnull=False) & ~models.Q(revoke_reason=""))
                ),
                name="accounts_session_revoke_reason_iff_revoked",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.client_type} session {self.pk} for {self.user_id}"


class RefreshToken(BaseModel):
    """A refresh token in a session's rotation chain (hash only, never the token).

    Each refresh marks the presented token ``rotated_at`` and issues a new one.
    Presenting an already-rotated token later means it was copied, so the whole
    session is revoked (docs/SECURITY.md §2.2).
    """

    session = models.ForeignKey(
        AuthSession, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField(help_text="Idle expiry of this token.")
    rotated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"refresh token {self.pk} of session {self.session_id}"


class OneTimeToken(BaseModel):
    """Single-use secret for an emailed link or a sign-in challenge.

    Only a SHA-256 hash is stored. A token is usable once, until it expires;
    issuing a new token for the same purpose invalidates older ones.
    """

    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "VERIFY_EMAIL", "Verify email address"
        RESET_PASSWORD = "RESET_PASSWORD", "Reset password"
        MFA_CHALLENGE = "MFA_CHALLENGE", "Second sign-in step"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="one_time_tokens")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["user", "purpose"],
                condition=models.Q(used_at__isnull=True),
                name="accounts_ott_open_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.purpose} token for {self.user_id}"


class TOTPDevice(BaseModel):
    """An authenticator app. The shared secret is encrypted at rest."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp_device")
    secret_encrypted = models.TextField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_counter = models.BigIntegerField(
        null=True, blank=True, help_text="Time step of the last accepted code (blocks replays)."
    )

    def __str__(self) -> str:
        return f"TOTP device of {self.user_id}"


class RecoveryCode(BaseModel):
    """One-time backup code for when the authenticator is unavailable (hash only)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["user", "code_hash"], name="accounts_recovery_unique"),
        ]

    def __str__(self) -> str:
        return f"recovery code of {self.user_id}"
