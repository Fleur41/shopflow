"""Throwaway views that exercise the error handling stack."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest
from django.urls import path
from rest_framework import exceptions, serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import ApplicationError


class ItemSerializer(serializers.Serializer[dict[str, object]]):
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=0)


class OrderSerializer(serializers.Serializer[dict[str, object]]):
    note = serializers.CharField()
    items = ItemSerializer(many=True)


class ValidateView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        OrderSerializer(data=request.data).is_valid(raise_exception=True)
        return Response({"ok": True})


class BusinessRuleView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        raise ApplicationError(
            '"Milk 500ml" only has 2 units in stock, but you tried to sell 5.',
            code="INSUFFICIENT_STOCK",
            title="Not enough stock",
            errors=[{"pointer": "/items/0/quantity", "code": "INSUFFICIENT_STOCK"}],
        )


class ThrottledView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        raise exceptions.Throttled(wait=12)


class NoCredentials(BaseAuthentication):
    """Stands in for the real authenticators added in Phase 1.5."""

    def authenticate(self, request: HttpRequest) -> None:
        return None

    def authenticate_header(self, request: HttpRequest) -> str:
        return "Bearer"


class ProtectedView(APIView):
    authentication_classes = (NoCredentials,)
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        return Response({"secret": "should not be reachable"})


class DjangoNotFoundView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        raise Http404("internal detail")


class DjangoForbiddenView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        raise DjangoPermissionDenied


class ConflictView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        raise ApplicationError("Prices changed.", code="PRICE_CHANGED", status_code=409)


class CrashView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        raise RuntimeError("boom")


urlpatterns = [
    path("validate/", ValidateView.as_view()),
    path("business-rule/", BusinessRuleView.as_view()),
    path("throttled/", ThrottledView.as_view()),
    path("protected/", ProtectedView.as_view()),
    path("crash/", CrashView.as_view()),
    path("django-404/", DjangoNotFoundView.as_view()),
    path("django-403/", DjangoForbiddenView.as_view()),
    path("conflict/", ConflictView.as_view()),
]

handler404 = "apps.common.views.not_found"
handler500 = "apps.common.views.server_error"
