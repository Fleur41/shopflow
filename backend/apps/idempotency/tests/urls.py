"""A test-only endpoint that requires an Idempotency-Key."""

from typing import ClassVar

from django.urls import include, path
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.errors import ApplicationError
from apps.idempotency.service import idempotent
from apps.organizations import services
from apps.organizations.api.permissions import TenantAPIView


class StrictCreateStoreView(TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "stores.manage"}

    @idempotent(required=True)
    def post(self, request: Request) -> Response:
        if request.data.get("fail"):
            services.create_store(self.ctx, code="FAIL1", name="Rolled back")
            raise ApplicationError("Simulated business rule failure.")
        store = services.create_store(self.ctx, code=request.data["code"], name="Strict")
        return Response({"id": str(store.pk), "code": store.code}, status=status.HTTP_201_CREATED)


urlpatterns = [
    path("strict-stores/", StrictCreateStoreView.as_view()),
    path("", include("config.urls")),
]
