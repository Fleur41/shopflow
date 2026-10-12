"""Store inventory endpoints (docs/API.md §4.4)."""

import uuid
from typing import Any, ClassVar

from django.db.models import Prefetch, QuerySet
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.catalog import images
from apps.catalog.models import Product
from apps.common.pagination import DefaultCursorPagination
from apps.common.params import datetime_param, uuid_param
from apps.idempotency.service import idempotent
from apps.organizations.api.store_scope import StoreScopedView

from .. import selectors, services
from ..models import InventoryMovement, StockAdjustment, StockAdjustmentLine
from .serializers import (
    AdjustmentCreateSerializer,
    AdjustmentSerializer,
    LookupSerializer,
    MovementSerializer,
    OpeningBalanceSerializer,
    StockRowSerializer,
    StockSettingsUpdateSerializer,
)


class _ByName(DefaultCursorPagination):
    ordering = ("name", "id")


class _ByRecorded(DefaultCursorPagination):
    ordering = ("-recorded_at", "-id")


class _ByOccurred(DefaultCursorPagination):
    ordering = ("-occurred_at", "-id")


INVENTORY_FILTERS = [
    OpenApiParameter("search", OpenApiTypes.STR, description="Name, SKU or exact barcode"),
    OpenApiParameter("category", OpenApiTypes.UUID),
    OpenApiParameter("supplier", OpenApiTypes.UUID),
    OpenApiParameter("stock_status", OpenApiTypes.STR, enum=list(selectors.STOCK_STATUSES)),
    OpenApiParameter("is_active", OpenApiTypes.BOOL),
]


class InventoryListView(mixins.ListModelMixin, StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "inventory.view"}
    serializer_class = StockRowSerializer
    pagination_class = _ByName

    def get_queryset(self) -> QuerySet[Product]:
        params = self.request.query_params
        is_active = params.get("is_active")
        return selectors.filter_stocked(
            selectors.stocked_products(self.ctx, self.store),
            search=params.get("search", "").strip(),
            category=uuid_param(self.request, "category"),
            supplier=uuid_param(self.request, "supplier"),
            stock_status=params.get("stock_status", ""),
            is_active=None if is_active is None else is_active.lower() == "true",
        )

    @extend_schema(parameters=INVENTORY_FILTERS)
    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        return self.list(request)


class StockLevelDetailView(StoreScopedView):
    # Each field of a PATCH needs its own permission, checked by the service.
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "inventory.view",
        "PATCH": "inventory.view",
    }
    serializer_class = StockSettingsUpdateSerializer

    def get_row(self, product_id: uuid.UUID) -> Product:
        row = selectors.stocked_products(self.ctx, self.store).filter(pk=product_id).first()
        if row is None:
            raise Http404
        return row

    @extend_schema(responses=StockRowSerializer, operation_id="stores_inventory_item_retrieve")
    def get(self, request: Request, store_id: uuid.UUID, product_id: uuid.UUID) -> Response:
        return Response(StockRowSerializer(self.get_row(product_id)).data)

    @extend_schema(responses=StockRowSerializer)
    def patch(self, request: Request, store_id: uuid.UUID, product_id: uuid.UUID) -> Response:
        product = self.get_row(product_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        version = changes.pop("version")
        services.update_stock_settings(self.ctx, self.store, product, version=version, **changes)
        return Response(StockRowSerializer(self.get_row(product_id)).data)


class LookupView(StoreScopedView):
    """The till's scan endpoint: exact barcode, then SKU."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": "inventory.view"}
    serializer_class = LookupSerializer

    @extend_schema(
        parameters=[OpenApiParameter("code", OpenApiTypes.STR, required=True)],
        responses=LookupSerializer,
    )
    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        found = selectors.lookup_code(self.ctx, self.store, request.query_params.get("code", ""))
        if found is None:
            raise Http404
        product = found.product
        level = found.level
        stocked = product.track_inventory
        return Response(
            LookupSerializer(
                {
                    "product_id": product.pk,
                    "name": product.name,
                    "sku": product.sku,
                    "unit": product.unit,
                    "tax_rate": f"{product.tax_rate.rate:.4f}",
                    "price": selectors.effective_price(product, level),
                    "pack_quantity": found.pack_quantity,
                    "track_inventory": stocked,
                    "quantity_on_hand": (level.quantity_on_hand if level else 0)
                    if stocked
                    else None,
                    "is_active": product.is_active,
                    "thumbnail_url": images.url_for(product.thumbnail_key),
                }
            ).data
        )


class MovementListView(mixins.ListModelMixin, StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "inventory.view_movements"}
    serializer_class = MovementSerializer
    pagination_class = _ByRecorded

    def get_queryset(self) -> QuerySet[InventoryMovement]:
        movements = (
            InventoryMovement.objects.for_org(self.ctx.organization)
            .filter(store=self.store)
            .select_related("product", "performed_by", "adjustment_line__adjustment")
        )
        params = self.request.query_params
        if product := uuid_param(self.request, "product"):
            movements = movements.filter(product_id=product)
        if user := uuid_param(self.request, "user"):
            movements = movements.filter(performed_by_id=user)
        if movement_type := params.get("type"):
            movements = movements.filter(movement_type=movement_type)
        if since := datetime_param(self.request, "from"):
            movements = movements.filter(occurred_at__gte=since)
        if until := datetime_param(self.request, "to"):
            movements = movements.filter(occurred_at__lt=until)
        return movements

    @extend_schema(
        parameters=[
            OpenApiParameter("product", OpenApiTypes.UUID),
            OpenApiParameter("user", OpenApiTypes.UUID),
            OpenApiParameter(
                "type", OpenApiTypes.STR, enum=[t.value for t in InventoryMovement.Type]
            ),
            OpenApiParameter("from", OpenApiTypes.DATETIME),
            OpenApiParameter("to", OpenApiTypes.DATETIME, description="Exclusive"),
        ]
    )
    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        return self.list(request)


def _adjustments(view: StoreScopedView) -> QuerySet[StockAdjustment]:
    lines = StockAdjustmentLine.unscoped.select_related("product").order_by("product__name")
    return (
        StockAdjustment.objects.for_org(view.ctx.organization)
        .filter(store=view.store)
        .select_related("created_by")
        .prefetch_related(Prefetch("lines", queryset=lines))
    )


class AdjustmentListView(mixins.ListModelMixin, StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "inventory.view_movements",
        "POST": "inventory.adjust",
    }
    pagination_class = _ByOccurred

    def get_serializer_class(self) -> type[serializers.Serializer[Any]]:
        if self.request.method == "POST":
            return AdjustmentCreateSerializer
        return AdjustmentSerializer

    def get_queryset(self) -> QuerySet[StockAdjustment]:
        return _adjustments(self)

    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        return self.list(request)

    @extend_schema(request=AdjustmentCreateSerializer, responses={201: AdjustmentSerializer})
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        adjustment = services.create_adjustment(
            self.ctx,
            self.store,
            client_txn_id=data["client_txn_id"],
            reason_code=data["reason_code"],
            note=data["note"],
            occurred_at=data.get("occurred_at"),
            lines=[services.AdjustmentLineInput(**line) for line in data["lines"]],
        )
        return _created(self, adjustment)


class AdjustmentDetailView(StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "inventory.view_movements"}
    serializer_class = AdjustmentSerializer

    def get(self, request: Request, store_id: uuid.UUID, adjustment_id: uuid.UUID) -> Response:
        adjustment = _adjustments(self).filter(pk=adjustment_id).first()
        if adjustment is None:
            raise Http404
        return Response(AdjustmentSerializer(adjustment).data)


class OpeningBalanceView(StoreScopedView):
    """Load a product's first stock in a store (``OPENING`` movements)."""

    required_permissions: ClassVar[dict[str, str]] = {"POST": "inventory.adjust"}
    serializer_class = OpeningBalanceSerializer

    @extend_schema(responses={201: AdjustmentSerializer})
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        adjustment = services.create_adjustment(
            self.ctx,
            self.store,
            client_txn_id=data["client_txn_id"],
            reason_code=StockAdjustment.Reason.OPENING_BALANCE,
            occurred_at=data.get("occurred_at"),
            lines=[
                services.AdjustmentLineInput(
                    product=line["product"],
                    counted_quantity=line["quantity"],
                    unit_cost=line.get("unit_cost"),
                )
                for line in data["lines"]
            ],
        )
        return _created(self, adjustment)


def _created(view: StoreScopedView, adjustment: StockAdjustment) -> Response:
    fresh: Any = _adjustments(view).get(pk=adjustment.pk)
    return Response(AdjustmentSerializer(fresh).data, status=status.HTTP_201_CREATED)
