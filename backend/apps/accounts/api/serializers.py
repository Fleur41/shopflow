from typing import Any

from rest_framework import serializers

from ..models import AuthSession, User


class ClientType:
    WEB = "web"
    MOBILE = "mobile"
    CHOICES = (WEB, MOBILE)


class LoginSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    client = serializers.ChoiceField(choices=ClientType.CHOICES, default=ClientType.WEB)
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True)


class MobileRefreshSerializer(serializers.Serializer[dict[str, Any]]):
    refresh_token = serializers.CharField(max_length=128, write_only=True)


class UserSerializer(serializers.ModelSerializer[User]):
    email_verified = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "phone", "email_verified")
        read_only_fields = fields

    def get_email_verified(self, user: User) -> bool:
        return user.email_verified_at is not None


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
