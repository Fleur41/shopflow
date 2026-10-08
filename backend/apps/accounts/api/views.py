"""Authentication endpoints (docs/API.md §4.1).

Web clients (``client: "web"``, the default) receive tokens only as HttpOnly
cookies and must send the CSRF token (from ``GET /auth/csrf/``) on every
state-changing request, including sign-in. Mobile clients receive tokens in
the response body and send ``Authorization: Bearer <access token>``.
"""

import uuid
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.middleware.csrf import get_token
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, BaseThrottle
from rest_framework.views import APIView

from .. import services
from ..authentication import enforce_csrf
from ..models import AuthSession, User
from ..tokens import AccessClaims
from .cookies import clear_auth_cookies, set_auth_cookies
from .serializers import (
    AuthResponseSerializer,
    ClientType,
    CsrfTokenSerializer,
    LoginSerializer,
    MobileRefreshSerializer,
    SessionSerializer,
    UserSerializer,
)
from .throttles import LoginEmailThrottle, LoginIPThrottle, RefreshThrottle

_CLIENT_TYPES = {
    ClientType.WEB: AuthSession.ClientType.WEB,
    ClientType.MOBILE: AuthSession.ClientType.MOBILE,
}


def _current_user(request: Request) -> User:
    if not isinstance(request.user, User):  # IsAuthenticated guarantees this
        raise NotAuthenticated
    return request.user


def _current_claims(request: Request) -> AccessClaims:
    if not isinstance(request.auth, AccessClaims):  # set by our authenticators
        raise NotAuthenticated
    return request.auth


def _client_ip(request: Request) -> str | None:
    # Same logic as the throttles, honouring REST_FRAMEWORK["NUM_PROXIES"].
    return BaseThrottle().get_ident(request) or None


def _token_payload(issued: services.IssuedTokens, *, include_tokens: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "user": issued.session.user,
        "session": {
            "id": issued.session.pk,
            "client_type": issued.session.client_type,
            "access_expires_at": issued.access_expires_at,
            "refresh_expires_at": issued.refresh_expires_at,
            "expires_at": issued.session.expires_at,
        },
    }
    if include_tokens:
        body["tokens"] = {
            "token_type": "Bearer",
            "access_token": issued.access_token,
            "refresh_token": issued.refresh_token,
        }
    return AuthResponseSerializer(body).data


class CsrfTokenView(APIView):
    """Issue the CSRF cookie and return its token for the ``X-CSRFToken`` header."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (AnonRateThrottle,)

    @extend_schema(responses=CsrfTokenSerializer)
    def get(self, request: Request) -> Response:
        return Response({"csrf_token": get_token(request._request)})


class LoginView(APIView):
    authentication_classes = ()  # credentials arrive in the body
    permission_classes = (AllowAny,)
    throttle_classes = (LoginIPThrottle, LoginEmailThrottle)

    @extend_schema(request=LoginSerializer, responses=AuthResponseSerializer)
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        is_web = data["client"] == ClientType.WEB
        if is_web:
            enforce_csrf(request)

        issued = services.login(
            email=data["email"],
            password=data["password"],
            client_type=_CLIENT_TYPES[data["client"]],
            ip_address=_client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            device_name=data.get("device_name", ""),
        )
        response = Response(_token_payload(issued, include_tokens=not is_web))
        if is_web:
            set_auth_cookies(response, issued)
        return response


class RefreshView(APIView):
    """Rotate the refresh token. Web: from the cookie. Mobile: ``refresh_token`` in the body."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (RefreshThrottle,)

    @extend_schema(
        request=MobileRefreshSerializer,
        responses=AuthResponseSerializer,
        description="Web clients send no body; the refresh token comes from the cookie.",
    )
    def post(self, request: Request) -> Response:
        if "refresh_token" in request.data:
            serializer = MobileRefreshSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            issued = services.refresh(
                refresh_token=serializer.validated_data["refresh_token"],
                client_type=AuthSession.ClientType.MOBILE,
            )
            return Response(_token_payload(issued, include_tokens=True))

        enforce_csrf(request)
        raw_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME, "")
        try:
            if not raw_token:
                raise services.RefreshTokenInvalid(
                    "Your session has expired. Please sign in again."
                )
            issued = services.refresh(
                refresh_token=raw_token, client_type=AuthSession.ClientType.WEB
            )
        except services.RefreshTokenInvalid as exc:
            response = self.handle_exception(exc)
            clear_auth_cookies(response)
            return response
        response = Response(_token_payload(issued, include_tokens=False))
        set_auth_cookies(response, issued)
        return response


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: OpenApiResponse(description="Signed out")})
    def post(self, request: Request) -> Response:
        services.logout(session_id=_current_claims(request).session_id)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)
        return response


class LogoutAllView(APIView):
    @extend_schema(request=None, responses={204: OpenApiResponse(description="All sessions ended")})
    def post(self, request: Request) -> Response:
        services.logout_all(user=_current_user(request))
        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_auth_cookies(response)
        return response


class MeView(APIView):
    @extend_schema(responses=UserSerializer)
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(_current_user(request)).data)


class SessionListView(generics.ListAPIView[AuthSession]):
    """The caller's active sessions; the one making the request has ``current: true``."""

    serializer_class = SessionSerializer

    def get_queryset(self) -> QuerySet[AuthSession]:
        return AuthSession.objects.filter(
            user=_current_user(self.request), revoked_at__isnull=True, expires_at__gt=timezone.now()
        )

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["current_session_id"] = _current_claims(self.request).session_id
        return context


class SessionRevokeView(APIView):
    @extend_schema(responses={204: OpenApiResponse(description="Session revoked")})
    def delete(self, request: Request, session_id: uuid.UUID) -> Response:
        services.revoke_user_session(user=_current_user(request), session_id=session_id)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        if session_id == _current_claims(request).session_id:
            clear_auth_cookies(response)
        return response
