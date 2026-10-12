"""Customer endpoints (docs/API.md §4.6)."""

import uuid
from typing import Any, ClassVar

from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.pagination import DefaultCursorPagination
from apps.idempotency.service import idempotent
from apps.organizations.api.master_data import (
    LIST_FILTERS,
    MasterDataDetailView,
    MasterDataListView,
    bool_param,
    patch_schema,
)
from apps.organizations.api.permissions import TenantAPIView
from apps.organizations.master_data import MasterData

from .. import services
from ..models import Customer, CustomerAccount, CustomerLedgerEntry
from .serializers import (
    AccountUpdateSerializer,
    CustomerAccountSummary,
    CustomerOpeningBalanceSerializer,
    CustomerSerializer,
    CustomerUpdateSerializer,
    LedgerEntrySerializer,
    PaymentCreateSerializer,
    ReverseSerializer,
)


def _with_accounts(ctx: Any, customers: QuerySet[Customer]) -> QuerySet[Customer]:
    return customers.prefetch_related(
        Prefetch(
            "accounts",
            queryset=CustomerAccount.unscoped.filter(currency=ctx.organization.base_currency),
            to_attr="prefetched_accounts",
        )
    )


class CustomerListView(MasterDataListView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "customers.view",
        "POST": "customers.create",
    }
    model = Customer
    serializer_class = CustomerSerializer
    search_fields = ("name", "phone")

    def get_queryset(self) -> QuerySet[Any]:
        customers = super().get_queryset()
        has_balance = bool_param(self.request, "has_balance")
        if has_balance is not None:
            owing = CustomerAccount.unscoped.filter(customer=OuterRef("pk"), balance__gt=0)
            customers = customers.filter(Exists(owing) if has_balance else ~Exists(owing))
        return _with_accounts(self.ctx, customers)

    def filter_search(self, entries: QuerySet[Any], search: str) -> QuerySet[Any]:
        digits = "".join(c for c in search if c.isdigit())
        matches = Q(name__icontains=search)
        if len(digits) >= 3:  # "0712 345" finds +254712345678
            matches |= Q(phone__contains=digits.removeprefix("0"))
        return entries.filter(matches)

    def create_entry(self, fields: dict[str, Any]) -> MasterData:
        return services.create_customer(self.ctx, **fields)

    @extend_schema(
        parameters=[
            *LIST_FILTERS,
            OpenApiParameter("has_balance", OpenApiTypes.BOOL, description="Owes money"),
        ]
    )
    def get(self, request: Request) -> Response:
        return self.list(request)


@patch_schema
class CustomerDetailView(MasterDataDetailView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "customers.view",
        "PATCH": "customers.manage",
    }
    model = Customer
    serializer_class = CustomerSerializer
    update_serializer_class = CustomerUpdateSerializer

    def get_entry(self, entry_id: uuid.UUID) -> Any:
        customers = Customer.objects.for_org(self.ctx.organization).filter(pk=entry_id)
        customer = _with_accounts(self.ctx, customers).first()
        if customer is None:
            raise Http404
        return customer


class _CustomerChild(TenantAPIView):
    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # Before other checks (e.g. a missing Idempotency-Key): not yours is a 404.
        self.get_customer(kwargs["customer_id"])

    def get_customer(self, customer_id: uuid.UUID) -> Customer:
        cached: Customer | None = getattr(self, "_customer", None)
        if cached is not None:
            return cached
        customer = Customer.objects.for_org(self.ctx.organization).filter(pk=customer_id).first()
        if customer is None:
            raise Http404
        self._customer = customer
        return customer


class AccountView(_CustomerChild):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": "customers.view_balance",
        "PATCH": "customers.set_credit_limit",
    }
    serializer_class = AccountUpdateSerializer

    @extend_schema(responses=CustomerAccountSummary)
    def get(self, request: Request, customer_id: uuid.UUID) -> Response:
        account = services.account_of(self.ctx, self.get_customer(customer_id))
        return Response(CustomerAccountSummary(account).data)

    @extend_schema(responses=CustomerAccountSummary)
    def patch(self, request: Request, customer_id: uuid.UUID) -> Response:
        customer = self.get_customer(customer_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        account = services.update_account(
            self.ctx, customer, version=changes.pop("version"), **changes
        )
        return Response(CustomerAccountSummary(account).data)


class OpeningBalanceView(_CustomerChild):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "customers.set_credit_limit"}
    serializer_class = CustomerOpeningBalanceSerializer

    @extend_schema(responses={201: LedgerEntrySerializer})
    @idempotent(required=True)
    def post(self, request: Request, customer_id: uuid.UUID) -> Response:
        customer = self.get_customer(customer_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = services.set_opening_balance(self.ctx, customer, **serializer.validated_data)
        return Response(LedgerEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class _ByNewest(DefaultCursorPagination):
    ordering = ("-seq",)


def _entries(view: _CustomerChild, customer: Customer) -> QuerySet[CustomerLedgerEntry]:
    account = services.account_of(view.ctx, customer)
    return (
        CustomerLedgerEntry.objects.for_org(view.ctx.organization)
        .filter(account=account)
        .select_related("created_by", "store", "sale", "reversed_by")
    )


class LedgerView(mixins.ListModelMixin, _CustomerChild):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "customers.view_balance"}
    serializer_class = LedgerEntrySerializer
    pagination_class = _ByNewest

    def get_queryset(self) -> QuerySet[CustomerLedgerEntry]:
        return _entries(self, self.get_customer(self.kwargs["customer_id"]))

    def get(self, request: Request, customer_id: uuid.UUID) -> Response:
        return self.list(request)


class PaymentView(_CustomerChild):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "customers.receive_payment"}
    serializer_class = PaymentCreateSerializer

    @extend_schema(responses={201: LedgerEntrySerializer})
    @idempotent(required=True)
    def post(self, request: Request, customer_id: uuid.UUID) -> Response:
        customer = self.get_customer(customer_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry, created = services.receive_payment(self.ctx, customer, **serializer.validated_data)
        return Response(
            LedgerEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ReverseEntryView(_CustomerChild):
    required_permissions: ClassVar[dict[str, str]] = {"POST": "customers.reverse_entry"}
    serializer_class = ReverseSerializer

    @extend_schema(responses={201: LedgerEntrySerializer})
    @idempotent(required=True)
    def post(self, request: Request, customer_id: uuid.UUID, entry_id: uuid.UUID) -> Response:
        entry = _entries(self, self.get_customer(customer_id)).filter(pk=entry_id).first()
        if entry is None:
            raise Http404
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reversal = services.reverse_entry(self.ctx, entry, **serializer.validated_data)
        return Response(LedgerEntrySerializer(reversal).data, status=status.HTTP_201_CREATED)
