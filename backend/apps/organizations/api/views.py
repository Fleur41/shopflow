"""Tenancy endpoints (docs/API.md sections 4.1 and 4.2).

Organization-scoped views extend :class:`TenantAPIView` and declare the
permission each HTTP method needs. Objects are always looked up within the
caller's organization (and accessible stores), so another business's IDs
return 404, exactly like IDs that do not exist.
"""

import dataclasses
import uuid
from typing import Any, ClassVar

from django.db.models import QuerySet
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.cookies import set_auth_cookies
from apps.accounts.api.serializers import AuthResponseSerializer, ClientType
from apps.accounts.api.views import auth_response_body
from apps.accounts.authentication import enforce_csrf
from apps.accounts.lifecycle import send_email_verification
from apps.accounts.models import AuthSession, User
from apps.accounts.services import (
    IssuedTokens,
    get_session_state,
    start_session,
    switch_organization,
)
from apps.accounts.tokens import AccessClaims
from apps.common.errors import StaleVersion
from apps.common.http import client_ip
from apps.idempotency.service import idempotent

from .. import invitations, selectors, services
from ..context import get_request_context
from ..errors import TenantAccessError
from ..models import Invitation, Membership, Permission, Role, Store
from .permissions import TenantAPIView
from .serializers import (
    InvitationAcceptedSerializer,
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationPreviewSerializer,
    InvitationSerializer,
    InvitationTokenSerializer,
    MemberCreateSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    MeSerializer,
    OrganizationSerializer,
    PermissionSerializer,
    RoleSerializer,
    SignupSerializer,
    StoreSerializer,
    StoreUpdateSerializer,
    SuspendSerializer,
    SwitchOrganizationSerializer,
)
from .throttles import InvitationTokenThrottle, SignupThrottle


def _session_response(issued: IssuedTokens, *, status_code: int = 200) -> Response:
    is_web = issued.session.client_type == AuthSession.ClientType.WEB
    response = Response(auth_response_body(issued, include_tokens=not is_web), status=status_code)
    if is_web:
        set_auth_cookies(response, issued)
    return response


# --- Sign-up, switching business, who am I ----------------------------------------------


class SignupView(APIView):
    """Create an account and a business in one step; the caller is signed in as its owner."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (SignupThrottle,)

    @extend_schema(request=SignupSerializer, responses={201: AuthResponseSerializer})
    def post(self, request: Request) -> Response:
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        is_web = data["client"] == ClientType.WEB
        if is_web:
            enforce_csrf(request)

        user_agent = request.headers.get("User-Agent", "")
        registered = services.register_business(
            email=data["email"],
            full_name=data["full_name"],
            password=data["password"],
            organization_name=data["organization_name"],
            currency=data["currency"],
            timezone=data["timezone"],
            store_name=data.get("store_name", ""),
            ip_address=client_ip(request),
            user_agent=user_agent,
        )
        send_email_verification(registered.user)
        issued = start_session(
            user=registered.user,
            client_type=AuthSession.ClientType.WEB if is_web else AuthSession.ClientType.MOBILE,
            organization_id=registered.organization.pk,
            ip_address=client_ip(request),
            user_agent=user_agent,
            device_name=data.get("device_name", ""),
        )
        return _session_response(issued, status_code=status.HTTP_201_CREATED)


class SwitchOrganizationView(APIView):
    """Start a new session in another of the user's businesses (the old one ends)."""

    @extend_schema(request=SwitchOrganizationSerializer, responses=AuthResponseSerializer)
    def post(self, request: Request) -> Response:
        serializer = SwitchOrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not isinstance(request.user, User) or not isinstance(request.auth, AccessClaims):
            raise Http404
        organization_id = serializer.validated_data["organization_id"]
        selectors.require_active_membership(request.user, organization_id)
        issued = switch_organization(
            session_id=request.auth.session_id, organization_id=organization_id
        )
        return _session_response(issued)


class MeView(APIView):
    """The signed-in user, the current business and what they may do in it."""

    @extend_schema(responses=MeSerializer)
    def get(self, request: Request) -> Response:
        user = request.user
        if not isinstance(user, User):
            raise Http404
        state = (
            get_session_state(request.auth.session_id)
            if isinstance(request.auth, AccessClaims)
            else None
        )
        body: dict[str, Any] = {
            "user": user,
            "organization": None,
            "access": None,
            "mfa_verified": bool(state and state.mfa_verified),
        }
        try:
            ctx = get_request_context(request)
        except TenantAccessError:
            ctx = None
        if ctx is not None:
            body["organization"] = ctx.organization
            body["access"] = {
                "role": ctx.role,
                "permissions": sorted(ctx.permissions),
                "all_stores": ctx.all_stores,
                "stores": list(selectors.accessible_stores(ctx)),
            }
        body["organizations"] = [
            {
                "organization_id": m.organization_id,
                "organization_name": m.organization.name,
                "role": m.role.name,
            }
            for m in selectors.active_memberships(user).select_related("organization", "role")
        ]
        return Response(MeSerializer(body).data)


# --- Organization -------------------------------------------------------------------


class OrganizationView(TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "org.view", "PATCH": "org.manage"}
    serializer_class = OrganizationSerializer

    def get(self, request: Request) -> Response:
        return Response(OrganizationSerializer(self.ctx.organization).data)

    def patch(self, request: Request) -> Response:
        serializer = OrganizationSerializer(self.ctx.organization, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        organization = services.update_organization(self.ctx, **serializer.validated_data)
        return Response(OrganizationSerializer(organization).data)


# --- Stores ---------------------------------------------------------------------------


class StoreListView(mixins.ListModelMixin, TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "stores.view", "POST": "stores.manage"}
    serializer_class = StoreSerializer

    def get_queryset(self) -> QuerySet[Store]:
        return selectors.accessible_stores(self.ctx)

    def get(self, request: Request) -> Response:
        return self.list(request)

    @idempotent(required=False)
    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = services.create_store(self.ctx, **serializer.validated_data)
        return Response(StoreSerializer(store).data, status=status.HTTP_201_CREATED)


class StoreDetailView(TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "stores.view",
        "PATCH": "stores.manage",
    }
    serializer_class = StoreUpdateSerializer

    def get_store(self, store_id: uuid.UUID) -> Store:
        store = selectors.accessible_stores(self.ctx).filter(pk=store_id).first()
        if store is None:
            raise Http404
        return store

    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        return Response(StoreSerializer(self.get_store(store_id)).data)

    def patch(self, request: Request, store_id: uuid.UUID) -> Response:
        store = self.get_store(store_id)
        serializer = self.get_serializer(store, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        store = services.update_store(self.ctx, store, **serializer.validated_data)
        return Response(StoreSerializer(store).data)


# --- Roles ------------------------------------------------------------------------------


class PermissionListView(TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "roles.view"}
    serializer_class = PermissionSerializer
    pagination_class = None

    def get(self, request: Request) -> Response:
        permissions = Permission.objects.order_by("code")
        return Response(PermissionSerializer(permissions, many=True).data)


class RoleListView(mixins.ListModelMixin, TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "roles.view", "POST": "roles.manage"}
    serializer_class = RoleSerializer

    def get_queryset(self) -> QuerySet[Role]:
        return selectors.roles(self.ctx)

    def get(self, request: Request) -> Response:
        return self.list(request)

    @idempotent(required=False)
    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        role = services.create_role(
            self.ctx,
            name=data["name"],
            description=data["description"],
            permissions=data["permission_codes"],
        )
        return Response(self.get_serializer(role).data, status=status.HTTP_201_CREATED)


class RoleDetailView(TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "roles.view", "PATCH": "roles.manage"}
    serializer_class = RoleSerializer

    def get_role(self, role_id: uuid.UUID) -> Role:
        role = selectors.roles(self.ctx).filter(pk=role_id).first()
        if role is None:
            raise Http404
        return role

    def get(self, request: Request, role_id: uuid.UUID) -> Response:
        return Response(self.get_serializer(self.get_role(role_id)).data)

    def patch(self, request: Request, role_id: uuid.UUID) -> Response:
        role = self.get_role(role_id)
        serializer = self.get_serializer(role, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        role = services.update_role(
            self.ctx,
            role,
            name=data.get("name"),
            description=data.get("description") if "description" in request.data else None,
            permissions=data.get("permission_codes"),
        )
        return Response(self.get_serializer(role).data)


# --- Members ----------------------------------------------------------------------------


class MemberListView(mixins.ListModelMixin, TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "users.view", "POST": "users.manage"}
    serializer_class = MemberSerializer

    def get_queryset(self) -> QuerySet[Membership]:
        return selectors.members(self.ctx)

    def get(self, request: Request) -> Response:
        return self.list(request)

    @extend_schema(request=MemberCreateSerializer, responses={201: MemberSerializer})
    @idempotent(required=False)
    def post(self, request: Request) -> Response:
        serializer = MemberCreateSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        membership = services.add_member(
            self.ctx,
            email=data["email"],
            full_name=data["full_name"],
            password=data["password"],
            role=data["role_id"],
            all_stores=data["all_stores"],
            stores=data["store_ids"],
        )
        return Response(
            MemberSerializer(selectors.members(self.ctx).get(pk=membership.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class _MemberView(TenantAPIView):
    serializer_class = MemberSerializer

    def get_member(self, member_id: uuid.UUID) -> Membership:
        membership = selectors.members(self.ctx).filter(pk=member_id).first()
        if membership is None:
            raise Http404
        return membership

    def respond(self, membership: Membership) -> Response:
        fresh = selectors.members(self.ctx).get(pk=membership.pk)
        return Response(MemberSerializer(fresh).data)


class MemberDetailView(_MemberView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "users.view", "PATCH": "users.manage"}

    def get(self, request: Request, member_id: uuid.UUID) -> Response:
        return Response(MemberSerializer(self.get_member(member_id)).data)

    @extend_schema(request=MemberUpdateSerializer, responses=MemberSerializer)
    def patch(self, request: Request, member_id: uuid.UUID) -> Response:
        membership = self.get_member(member_id)
        serializer = MemberUpdateSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["version"] != membership.version:
            raise StaleVersion("Someone else changed this member. Reload and try again.")
        membership = services.update_member(
            self.ctx,
            membership,
            role=data.get("role_id"),
            all_stores=data.get("all_stores"),
            stores=data.get("store_ids"),
        )
        return self.respond(membership)


class MemberSuspendView(_MemberView):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "users.manage"}

    @extend_schema(request=SuspendSerializer, responses=MemberSerializer)
    def post(self, request: Request, member_id: uuid.UUID) -> Response:
        serializer = SuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.suspend_member(
            self.ctx, self.get_member(member_id), reason=serializer.validated_data["reason"]
        )
        return self.respond(membership)


class MemberReactivateView(_MemberView):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "users.manage"}

    @extend_schema(request=None, responses=MemberSerializer)
    def post(self, request: Request, member_id: uuid.UUID) -> Response:
        membership = services.reactivate_member(self.ctx, self.get_member(member_id))
        return self.respond(membership)


# --- Invitations ------------------------------------------------------------------


class InvitationListView(mixins.ListModelMixin, TenantAPIView):
    """Pending (and expired, not yet replaced) invitations."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": "users.view", "POST": "users.manage"}
    serializer_class = InvitationSerializer

    def get_queryset(self) -> QuerySet[Invitation]:
        return (
            Invitation.objects.for_org(self.ctx.organization)
            .filter(accepted_at__isnull=True, revoked_at__isnull=True)
            .select_related("role", "invited_by")
        )

    def get(self, request: Request) -> Response:
        return self.list(request)

    @extend_schema(request=InvitationCreateSerializer, responses={201: InvitationSerializer})
    @idempotent(required=False)
    def post(self, request: Request) -> Response:
        serializer = InvitationCreateSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invitation = invitations.invite_member(
            self.ctx,
            email=data["email"],
            role=data["role_id"],
            all_stores=data["all_stores"],
            stores=data["store_ids"],
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class InvitationRevokeView(TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "users.manage"}
    serializer_class = InvitationSerializer

    @extend_schema(request=None, responses=InvitationSerializer)
    def post(self, request: Request, invitation_id: uuid.UUID) -> Response:
        invitation = (
            Invitation.objects.for_org(self.ctx.organization).filter(pk=invitation_id).first()
        )
        if invitation is None:
            raise Http404
        return Response(
            InvitationSerializer(invitations.revoke_invitation(self.ctx, invitation)).data
        )


class InvitationPreviewView(APIView):
    """What an invitation link is for (the token itself is the credential)."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (InvitationTokenThrottle,)

    @extend_schema(request=InvitationTokenSerializer, responses=InvitationPreviewSerializer)
    def post(self, request: Request) -> Response:
        serializer = InvitationTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        preview = invitations.preview(serializer.validated_data["token"])
        return Response(InvitationPreviewSerializer(dataclasses.asdict(preview)).data)


class InvitationAcceptView(APIView):
    """Accept an invitation.

    New people send their name and a password: their account is created and
    they are signed in to the business (201). People with an account must be
    signed in as the invited email; they get the business ID to switch to (200).
    """

    permission_classes = (AllowAny,)
    throttle_classes = (InvitationTokenThrottle,)

    @extend_schema(
        request=InvitationAcceptSerializer,
        responses={201: AuthResponseSerializer, 200: InvitationAcceptedSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        signed_in = request.user if isinstance(request.user, User) else None
        is_web = data["client"] == ClientType.WEB
        if signed_in is None and is_web:
            enforce_csrf(request)  # we are about to set session cookies
        membership = invitations.accept_invitation(
            data["token"],
            signed_in_user=signed_in,
            full_name=data.get("full_name", ""),
            password=data.get("password"),
        )
        if signed_in is not None:
            return Response({"organization_id": str(membership.organization_id)})
        issued = start_session(
            user=membership.user,
            client_type=AuthSession.ClientType.WEB if is_web else AuthSession.ClientType.MOBILE,
            organization_id=membership.organization_id,
            ip_address=client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return _session_response(issued, status_code=status.HTTP_201_CREATED)
