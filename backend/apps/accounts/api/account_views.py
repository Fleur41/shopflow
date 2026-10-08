"""Account lifecycle endpoints: email verification, passwords, two-step verification.

Public endpoints (verify, reset, MFA verify) are throttled and never reveal
whether an email address has an account.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from .. import lifecycle
from ..authentication import enforce_csrf
from ..models import AuthSession, User, normalize_email_address
from ..services import email_fingerprint
from ..tokens import AccessClaims
from .cookies import set_auth_cookies
from .serializers import (
    AuthResponseSerializer,
    EmailVerifySerializer,
    MFAVerifySerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RecoveryCodesSerializer,
    TOTPConfirmSerializer,
    TOTPDisableSerializer,
    TOTPSetupSerializer,
)
from .views import auth_response_body


def _caller(request: Request) -> tuple[User, AccessClaims]:
    if not isinstance(request.user, User) or not isinstance(request.auth, AccessClaims):
        raise NotAuthenticated
    return request.user, request.auth


class _ScopedIPThrottle(SimpleRateThrottle):
    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PasswordResetIPThrottle(_ScopedIPThrottle):
    scope = "password_reset_ip"


class MFAVerifyThrottle(_ScopedIPThrottle):
    scope = "mfa_verify"


class PasswordResetEmailThrottle(SimpleRateThrottle):
    scope = "password_reset_email"

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        email = request.data.get("email") if hasattr(request.data, "get") else None
        if not isinstance(email, str) or not email.strip():
            return None
        ident = email_fingerprint(normalize_email_address(email))
        return self.cache_format % {"scope": self.scope, "ident": ident}


class EmailVerificationThrottle(SimpleRateThrottle):
    scope = "email_verification"

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": str(request.user.pk)}


_ACCEPTED = OpenApiResponse(description="Accepted")
_DONE = OpenApiResponse(description="Done")


class EmailVerificationRequestView(APIView):
    """Send (again) the link that confirms the signed-in user's email address."""

    throttle_classes = (EmailVerificationThrottle,)

    @extend_schema(request=None, responses={202: _ACCEPTED})
    def post(self, request: Request) -> Response:
        user, _ = _caller(request)
        lifecycle.send_email_verification(user)
        return Response(status=status.HTTP_202_ACCEPTED)


class EmailVerifyView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(request=EmailVerifySerializer, responses={200: _DONE})
    def post(self, request: Request) -> Response:
        serializer = EmailVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lifecycle.verify_email(serializer.validated_data["token"])
        return Response({"verified": True})


class PasswordResetView(APIView):
    """Always 202, whether or not the address has an account."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (PasswordResetIPThrottle, PasswordResetEmailThrottle)

    @extend_schema(request=PasswordResetSerializer, responses={202: _ACCEPTED})
    def post(self, request: Request) -> Response:
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lifecycle.request_password_reset(serializer.validated_data["email"])
        return Response(status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (PasswordResetIPThrottle,)

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: _DONE})
    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lifecycle.confirm_password_reset(data["token"], data["new_password"])
        return Response({"detail": "Your password was changed. Sign in with your new password."})


class PasswordChangeView(APIView):
    @extend_schema(request=PasswordChangeSerializer, responses={204: _DONE})
    def post(self, request: Request) -> Response:
        user, claims = _caller(request)
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lifecycle.change_password(
            user,
            session_id=claims.session_id,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TOTPSetupView(APIView):
    """Start authenticator-app setup: returns the secret and a QR code to scan."""

    @extend_schema(request=None, responses=TOTPSetupSerializer)
    def post(self, request: Request) -> Response:
        user, _ = _caller(request)
        setup = lifecycle.begin_totp_setup(user)
        return Response(
            TOTPSetupSerializer(
                {"secret": setup.secret, "otpauth_uri": setup.otpauth_uri, "qr_code": setup.qr_code}
            ).data
        )


class TOTPConfirmView(APIView):
    """Confirm with a first code. Returns recovery codes once; other sessions end."""

    @extend_schema(request=TOTPConfirmSerializer, responses=RecoveryCodesSerializer)
    def post(self, request: Request) -> Response:
        user, claims = _caller(request)
        serializer = TOTPConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codes = lifecycle.confirm_totp(
            user, session_id=claims.session_id, code=serializer.validated_data["code"]
        )
        return Response(RecoveryCodesSerializer({"recovery_codes": codes}).data)


class TOTPDisableView(APIView):
    @extend_schema(request=TOTPDisableSerializer, responses={204: _DONE})
    def post(self, request: Request) -> Response:
        user, claims = _caller(request)
        serializer = TOTPDisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lifecycle.disable_totp(
            user,
            session_id=claims.session_id,
            password=serializer.validated_data["password"],
            code=serializer.validated_data["code"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MFAVerifyView(APIView):
    """Second sign-in step after ``401 MFA_REQUIRED``: a 6-digit or recovery code."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (MFAVerifyThrottle,)

    @extend_schema(request=MFAVerifySerializer, responses=AuthResponseSerializer)
    def post(self, request: Request) -> Response:
        serializer = MFAVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["client"] == "web":
            enforce_csrf(request)
        issued = lifecycle.complete_mfa_login(data["mfa_token"], data["code"])
        is_web = issued.session.client_type == AuthSession.ClientType.WEB
        response = Response(auth_response_body(issued, include_tokens=not is_web))
        if is_web:
            set_auth_cookies(response, issued)
        return response
