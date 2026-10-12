"""Till and till-session endpoints (docs/API.md §4.5a)."""

import uuid
from typing import Any, ClassVar

from django.db.models import QuerySet
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.errors import StaleVersion
from apps.common.pagination import DefaultCursorPagination
from apps.idempotency.service import idempotent
from apps.organizations.access import require_permission
from apps.organizations.api.store_scope import StoreScopedView

from .. import services
from ..models import CashMovement, CashSession, Till
from .serializers import (
    CashSessionSerializer,
    CashSessionSummarySerializer,
    CloseSessionSerializer,
    CorrectionSerializer,
    CurrentSessionSerializer,
    MovementCreateSerializer,
    OpenSessionSerializer,
    SessionReportSerializer,
    TillSerializer,
    TillUpdateSerializer,
)


class TillListView(StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "cash.open_session",
        "POST": "stores.manage",
    }
    serializer_class = TillSerializer
    pagination_class = None

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "store": self.store}

    @extend_schema(responses=TillSerializer(many=True))
    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        tills = (
            Till.objects.for_org(self.ctx.organization).filter(store=self.store).order_by("name")
        )
        return Response(self.get_serializer(tills, many=True).data)

    @idempotent(required=False)
    def post(self, request: Request, store_id: uuid.UUID) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        till = Till.objects.create(
            organization=self.ctx.organization, store=self.store, **serializer.validated_data
        )
        return Response(self.get_serializer(till).data, status=status.HTTP_201_CREATED)


class TillDetailView(StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {"PATCH": "stores.manage"}
    serializer_class = TillUpdateSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "store": self.store}

    @extend_schema(responses=TillSerializer)
    def patch(self, request: Request, store_id: uuid.UUID, till_id: uuid.UUID) -> Response:
        till = (
            Till.objects.for_org(self.ctx.organization).filter(store=self.store, pk=till_id).first()
        )
        if till is None:
            raise Http404
        serializer = self.get_serializer(till, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        if changes.pop("version", None) != till.version:
            raise StaleVersion("Someone else changed this. Reload and try again.")
        for name, value in changes.items():
            setattr(till, name, value)
        till.version += 1
        till.save()
        return Response(TillSerializer(till, context=self.get_serializer_context()).data)


class _ByOpened(DefaultCursorPagination):
    ordering = ("-opened_at", "-id")


def _sessions(view: StoreScopedView) -> QuerySet[CashSession]:
    return (
        CashSession.objects.for_org(view.ctx.organization)
        .filter(store=view.store)
        .select_related("till", "opened_by", "closed_by", "store")
    )


class SessionListView(mixins.ListModelMixin, StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "cash.view_sessions",
        "POST": "cash.open_session",
    }
    pagination_class = _ByOpened

    def get_serializer_class(self) -> type[serializers.Serializer[Any]]:
        if self.request.method == "POST":
            return OpenSessionSerializer
        return CashSessionSummarySerializer

    def get_queryset(self) -> QuerySet[CashSession]:
        sessions = _sessions(self)
        if status_filter := self.request.query_params.get("status"):
            sessions = sessions.filter(status=status_filter)
        return sessions

    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        return self.list(request)

    @extend_schema(request=OpenSessionSerializer, responses={201: CashSessionSerializer})
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        till = Till.objects.for_org(self.ctx.organization).filter(pk=data["till_id"]).first()
        if till is None:
            raise serializers.ValidationError({"till_id": ["Choose a till in this store."]})
        session = services.open_session(
            self.ctx,
            self.store,
            till=till,
            opening_float=data["opening_float"],
            client_txn_id=data["client_txn_id"],
        )
        return Response(CashSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class CurrentSessionView(StoreScopedView):
    """The caller's open session here, without expected cash (the count is blind)."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": "cash.open_session"}
    serializer_class = CurrentSessionSerializer

    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        session = services.current_session(self.ctx, self.store)
        return Response(CurrentSessionSerializer({"session": session}).data)


class _SessionView(StoreScopedView):
    def get_session(self, session_id: uuid.UUID) -> CashSession:
        session = _sessions(self).filter(pk=session_id).first()
        if session is None:
            raise Http404
        return session

    def require_own_or_manager(self, session: CashSession) -> None:
        """Your own till, or anyone's if you oversee the store's tills."""
        if session.opened_by_id != self.ctx.user.pk:
            require_permission(self.ctx, "cash.view_sessions")


def _report(session: CashSession) -> dict[str, Any]:
    movements = (
        CashMovement.objects.for_org(session.organization_id)
        .filter(session=session)
        .select_related("created_by")
        .order_by("occurred_at")
    )
    return {"session": session, "report": services.report(session), "movements": movements}


class SessionDetailView(_SessionView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "cash.view_sessions"}
    serializer_class = SessionReportSerializer

    def get(self, request: Request, store_id: uuid.UUID, session_id: uuid.UUID) -> Response:
        return Response(SessionReportSerializer(_report(self.get_session(session_id))).data)


class MovementView(_SessionView):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "cash.pay_in_out"}
    serializer_class = MovementCreateSerializer

    @extend_schema(responses={201: CashSessionSerializer})
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID, session_id: uuid.UUID) -> Response:
        session = self.get_session(session_id)
        self.require_own_or_manager(session)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_movement(self.ctx, session, **serializer.validated_data)
        return Response(CashSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class CloseView(_SessionView):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "cash.close_session"}
    serializer_class = CloseSessionSerializer

    @extend_schema(responses=SessionReportSerializer)
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID, session_id: uuid.UUID) -> Response:
        session = self.get_session(session_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        closed = services.close_session(self.ctx, session, **serializer.validated_data)
        # The Z report: the cashier sees the result only after committing their count.
        return Response(SessionReportSerializer(_report(closed)).data)


class CorrectionView(_SessionView):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "cash.correct"}
    serializer_class = CorrectionSerializer

    @extend_schema(responses={201: SessionReportSerializer})
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID, session_id: uuid.UUID) -> Response:
        session = self.get_session(session_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_movement(
            self.ctx, session, movement_type="CORRECTION", **serializer.validated_data
        )
        return Response(
            SessionReportSerializer(_report(self.get_session(session_id))).data,
            status=status.HTTP_201_CREATED,
        )
