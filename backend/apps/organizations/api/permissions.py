from collections.abc import Mapping
from typing import Any, ClassVar

from django.conf import settings
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.views import APIView

from ..catalog import SENSITIVE_CODES
from ..context import RequestContext, get_request_context
from ..errors import MFAEnrollmentRequired, MissingPermission


class TenantPermission(BasePermission):
    """Resolve the tenant context and check the permission the view declares.

    Views declare ``required_permissions = {"GET": "stores.view", ...}``. A
    method without a declaration is denied (fail closed); a test also fails
    the build for undeclared methods.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        ctx = get_request_context(request)
        method = "GET" if request.method == "HEAD" else str(request.method)
        if method == "OPTIONS":
            return True
        required: Mapping[str, str] = getattr(view, "required_permissions", {})
        code = required.get(method)
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
        return True


class TenantAPIView(GenericAPIView):  # type: ignore[type-arg]
    """Base for every organization-scoped endpoint."""

    permission_classes = (IsAuthenticated, TenantPermission)
    required_permissions: ClassVar[Mapping[str, str]] = {}

    @property
    def ctx(self) -> RequestContext:
        return get_request_context(self.request)

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["ctx"] = self.ctx
        return context
