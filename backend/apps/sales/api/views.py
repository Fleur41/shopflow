"""Sale endpoints (docs/API.md §4.5)."""

import uuid
from decimal import Decimal
from typing import Any, ClassVar

from django.db.models import Count, Prefetch, Q, QuerySet
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.common.currency import minor_units
from apps.common.pagination import DefaultCursorPagination
from apps.common.params import datetime_param, uuid_param
from apps.customers.models import CustomerLedgerEntry
from apps.idempotency.service import idempotent
from apps.organizations.api.master_data import bool_param
from apps.organizations.api.store_scope import StoreScopedView
from apps.payments.models import Payment

from .. import reversals, services
from ..models import Sale, SaleItem, SaleReturn, SaleReturnItem
from .serializers import (
    ReceiptSerializer,
    ReturnCreateSerializer,
    SaleCreateSerializer,
    SaleListSerializer,
    SaleReturnSerializer,
    SaleSerializer,
    VoidSerializer,
)


class _ByNewest(DefaultCursorPagination):
    ordering = ("-occurred_at", "-id")


def _sales(view: StoreScopedView) -> QuerySet[Sale]:
    """Sales of this store the caller may see: all, or only their own."""
    sales = Sale.objects.for_org(view.ctx.organization).filter(store=view.store)
    if not view.ctx.has_perm("sales.view_all"):
        sales = sales.filter(cashier=view.ctx.user)
    return sales


def _returns() -> QuerySet[SaleReturn]:
    return (
        SaleReturn.unscoped.select_related("created_by")
        .prefetch_related(
            Prefetch("items", queryset=SaleReturnItem.unscoped.select_related("sale_item")),
            Prefetch(
                "refunds",
                queryset=Payment.unscoped.select_related("payment_method"),
                to_attr="refunds_list",
            ),
        )
        .order_by("occurred_at")
    )


def _full(sales: QuerySet[Sale]) -> QuerySet[Sale]:
    return sales.select_related("store", "cashier", "customer", "voided_by").prefetch_related(
        Prefetch(
            "items",
            queryset=SaleItem.unscoped.order_by("line_no").prefetch_related(
                Prefetch("returned", queryset=SaleReturnItem.unscoped.all())
            ),
        ),
        Prefetch(
            "payments",
            queryset=Payment.unscoped.select_related("payment_method").order_by(
                "direction", "position"
            ),
        ),
        Prefetch("returns", queryset=_returns()),
    )


class SaleListView(mixins.ListModelMixin, StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "sales.view_own",
        "POST": "sales.create",
    }
    pagination_class = _ByNewest

    def get_serializer_class(self) -> type[serializers.Serializer[Any]]:
        if self.request.method == "POST":
            return SaleCreateSerializer
        return SaleListSerializer

    def get_queryset(self) -> QuerySet[Sale]:
        request = self.request
        sales = _sales(self).select_related("cashier", "customer")
        if search := request.query_params.get("search", "").strip():
            sales = sales.filter(receipt_number__icontains=search)
        if cashier := uuid_param(request, "cashier"):
            sales = sales.filter(cashier_id=cashier)
        if customer := uuid_param(request, "customer"):
            sales = sales.filter(customer_id=customer)
        on_credit = bool_param(request, "on_credit")
        if on_credit is not None:
            sales = sales.filter(Q(amount_on_credit__gt=0) if on_credit else Q(amount_on_credit=0))
        if since := datetime_param(request, "from"):
            sales = sales.filter(occurred_at__gte=since)
        if until := datetime_param(request, "to"):
            sales = sales.filter(occurred_at__lt=until)
        return sales.annotate(item_count=Count("items")).prefetch_related(
            Prefetch("payments", queryset=Payment.unscoped.select_related("payment_method"))
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, description="Receipt number"),
            OpenApiParameter("cashier", OpenApiTypes.UUID),
            OpenApiParameter("customer", OpenApiTypes.UUID),
            OpenApiParameter("on_credit", OpenApiTypes.BOOL),
            OpenApiParameter("from", OpenApiTypes.DATETIME),
            OpenApiParameter("to", OpenApiTypes.DATETIME, description="Exclusive"),
        ],
    )
    def get(self, request: Request, store_id: uuid.UUID) -> Response:
        return self.list(request)

    @extend_schema(
        request=SaleCreateSerializer, responses={201: SaleSerializer, 200: SaleSerializer}
    )
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.create_sale(
            self.ctx,
            self.store,
            services.SaleRequest(
                client_txn_id=data["client_txn_id"],
                occurred_at=data.get("occurred_at"),
                customer=data["customer"],
                items=[services.ItemInput(**item) for item in data["items"]],
                tenders=[services.TenderInput(**tender) for tender in data["tenders"]],
                order_discount=data["order_discount"],
                credit_amount=data["credit_amount"],
                notes=data["notes"],
                cash_session_id=data["cash_session_id"],
            ),
        )
        sale = _full(Sale.objects.for_org(self.ctx.organization)).get(pk=result.sale.pk)
        return Response(
            SaleSerializer(sale).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class SaleDetailView(StoreScopedView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "sales.view_own"}
    serializer_class = SaleSerializer

    def get(self, request: Request, store_id: uuid.UUID, sale_id: uuid.UUID) -> Response:
        sale = _full(_sales(self)).filter(pk=sale_id).first()
        if sale is None:
            raise Http404
        return Response(SaleSerializer(sale).data)


class ReceiptView(StoreScopedView):
    """The data a printed receipt shows. ``?reprint=true`` marks (and audits) a copy."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": "sales.view_own"}
    serializer_class = ReceiptSerializer

    @extend_schema(parameters=[OpenApiParameter("reprint", OpenApiTypes.BOOL)])
    def get(self, request: Request, store_id: uuid.UUID, sale_id: uuid.UUID) -> Response:
        sale = _full(_sales(self)).filter(pk=sale_id).first()
        if sale is None:
            raise Http404
        reprint = bool(bool_param(request, "reprint"))
        if reprint:
            record_audit(
                self.ctx.audit_actor,
                action="sale.receipt_reprinted",
                entity_type="sale",
                entity_id=sale.pk,
                store_id=sale.store_id,
            )
        return Response(ReceiptSerializer(receipt_data(self, sale, reprint=reprint)).data)


def receipt_data(view: StoreScopedView, sale: Sale, *, reprint: bool) -> dict[str, Any]:
    places = minor_units(sale.currency)

    def fmt(amount: Decimal) -> str:
        return f"{amount:.{places}f}"

    taxes: dict[tuple[str, Decimal], list[Decimal]] = {}
    for item in sale.items.all():
        bucket = taxes.setdefault((item.tax_name, item.tax_rate), [Decimal(0), Decimal(0)])
        bucket[0] += item.line_total - item.tax_amount
        bucket[1] += item.tax_amount
    account = None
    if sale.amount_on_credit > 0:
        entry = (
            CustomerLedgerEntry.objects.for_org(view.ctx.organization)
            .filter(sale=sale, entry_type=CustomerLedgerEntry.Type.CREDIT_SALE)
            .first()
        )
        if entry is not None and view.ctx.has_perm("customers.view_balance"):
            account = {"charged": fmt(entry.amount), "balance_after": fmt(entry.balance_after)}
    store = sale.store
    return {
        "business": {
            "name": view.ctx.organization.name,
            "store_name": store.name,
            "address": store.address,
            "phone": store.phone,
            "timezone": store.timezone,
        },
        "sale": sale,
        "taxes": [
            {
                "name": name,
                "rate": f"{rate:.4f}",
                "taxable_amount": fmt(taxable),
                "tax_amount": fmt(tax),
            }
            for (name, rate), (taxable, tax) in sorted(taxes.items(), key=lambda kv: -kv[0][1])
        ],
        "account": account,
        "reprint": reprint,
    }


class _SaleAction(StoreScopedView):
    def get_sale(self, sale_id: uuid.UUID) -> Sale:
        sale = _sales(self).filter(pk=sale_id).first()
        if sale is None:
            raise Http404
        return sale

    def full(self, sale: Sale) -> Response:
        return Response(
            SaleSerializer(_full(Sale.objects.for_org(self.ctx.organization)).get(pk=sale.pk)).data
        )


class VoidView(_SaleAction):
    """Undo today's sale while its till is still open: stock, money and credit go back."""

    required_permissions: ClassVar[dict[str, str]] = {"POST": "sales.void"}
    serializer_class = VoidSerializer

    @extend_schema(responses=SaleSerializer)
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID, sale_id: uuid.UUID) -> Response:
        sale = self.get_sale(sale_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reversals.void_sale(self.ctx, sale, reason=serializer.validated_data["reason"])
        return self.full(sale)


class ReturnsView(_SaleAction):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "sales.view_own",
        "POST": "sales.return",
    }
    serializer_class = ReturnCreateSerializer

    @extend_schema(responses=SaleReturnSerializer(many=True))
    def get(self, request: Request, store_id: uuid.UUID, sale_id: uuid.UUID) -> Response:
        sale = self.get_sale(sale_id)
        returns = _returns().filter(organization=self.ctx.organization, sale=sale)
        return Response(SaleReturnSerializer(returns, many=True).data)

    @extend_schema(responses={201: SaleSerializer, 200: SaleSerializer})
    @idempotent(required=True)
    def post(self, request: Request, store_id: uuid.UUID, sale_id: uuid.UUID) -> Response:
        sale = self.get_sale(sale_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        items = {
            item.line_no: item
            for item in SaleItem.objects.for_org(self.ctx.organization)
            .filter(sale=sale)
            .select_related("product__unit")
        }
        lines = []
        for index, line in enumerate(data["items"]):
            item = items.get(line["line_no"])
            if item is None:
                raise serializers.ValidationError(
                    {"items": {str(index): {"line_no": ["This sale has no such line."]}}}
                )
            lines.append(reversals.ReturnLine(item, line["quantity"], line["restock"]))
        result = reversals.return_items(
            self.ctx,
            self.store,
            sale,
            client_txn_id=data["client_txn_id"],
            reason=data["reason"],
            lines=lines,
            refund_to=data["refund_to"],
            payment_method=data["payment_method"],
            cash_session_id=data["cash_session_id"],
        )
        response = self.full(sale)
        response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return response
