from typing import Any

from rest_framework import serializers

from ..models import AuthSession, TOTPDevice, User


class ClientType:
    WEB = "web"
    MOBILE = "mobile"
    CHOICES = (WEB, MOBILE)


class LoginSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    client = serializers.ChoiceField(choices=ClientType.CHOICES, default=ClientType.WEB)
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    organization_id = serializers.UUIDField(
        required=False,
        help_text="Business to work in. Optional when the user belongs to exactly one.",
    )


class MobileRefreshSerializer(serializers.Serializer[dict[str, Any]]):
    refresh_token = serializers.CharField(max_length=128, write_only=True)


class UserSerializer(serializers.ModelSerializer[User]):
    email_verified = serializers.SerializerMethodField()
    mfa_enabled = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "phone", "email_verified", "mfa_enabled")
        read_only_fields = fields

    def get_email_verified(self, user: User) -> bool:
        return user.email_verified_at is not None

    def get_mfa_enabled(self, user: User) -> bool:
        return TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


class SessionSerializer(serializers.ModelSerializer[AuthSession]):
    current = serializers.SerializerMethodField()

    class Meta:
        model = AuthSession
        fields = (
            "id",
            "client_type",
            "device_name",
            "user_agent",
            "ip_address",
            "created_at",
            "last_used_at",
            "expires_at",
            "current",
        )
        read_only_fields = fields

    def get_current(self, session: AuthSession) -> bool:
        return session.pk == self.context.get("current_session_id")


# --- Response shapes (also the OpenAPI schema for generated clients) ---------


class CsrfTokenSerializer(serializers.Serializer[dict[str, Any]]):
    csrf_token = serializers.CharField()


class SessionInfoSerializer(serializers.Serializer[dict[str, Any]]):
    id = serializers.UUIDField()
    client_type = serializers.ChoiceField(choices=AuthSession.ClientType.choices)
    access_expires_at = serializers.DateTimeField()
    refresh_expires_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(help_text="Absolute end of the session.")


class TokenPairSerializer(serializers.Serializer[dict[str, Any]]):
    token_type = serializers.CharField()
    access_token = serializers.CharField()
    refresh_token = serializers.CharField()


class AuthResponseSerializer(serializers.Serializer[dict[str, Any]]):
    user = UserSerializer()
    session = SessionInfoSerializer()
    tokens = TokenPairSerializer(
        required=False, help_text="Mobile clients only. Web clients receive HttpOnly cookies."
    )


# --- Account lifecycle ----------------------------------------------------------


class EmailVerifySerializer(serializers.Serializer[dict[str, Any]]):
    token = serializers.CharField(max_length=128)


class PasswordResetSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer[dict[str, Any]]):
    token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


class PasswordChangeSerializer(serializers.Serializer[dict[str, Any]]):
    current_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)


class TOTPSetupSerializer(serializers.Serializer[dict[str, Any]]):
    secret = serializers.CharField(help_text="Base32 secret for manual entry.")
    otpauth_uri = serializers.CharField()
    qr_code = serializers.CharField(help_text="PNG QR code as a data: URI.")


class TOTPConfirmSerializer(serializers.Serializer[dict[str, Any]]):
    code = serializers.CharField(max_length=16)


class RecoveryCodesSerializer(serializers.Serializer[dict[str, Any]]):
    recovery_codes = serializers.ListField(
        child=serializers.CharField(), help_text="Shown once. Each works one time."
    )


class TOTPDisableSerializer(serializers.Serializer[dict[str, Any]]):
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)
    code = serializers.CharField(max_length=32, help_text="Authenticator or recovery code.")


class MFAVerifySerializer(serializers.Serializer[dict[str, Any]]):
    mfa_token = serializers.CharField(max_length=128)
    code = serializers.CharField(max_length=32, help_text="Authenticator or recovery code.")
    client = serializers.ChoiceField(choices=ClientType.CHOICES, default=ClientType.WEB)
