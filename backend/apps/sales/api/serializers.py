from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.organizations.api.serializers import ScopedPrimaryKeyField
from apps.payments.models import Payment, PaymentMethod

from ..models import Sale, SaleItem


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=19, decimal_places=4, **kwargs)


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=3, **kwargs)


# --- Create -----------------------------------------------------------------------------------


class _ItemInput(serializers.Serializer[Any]):
    product_id = ScopedPrimaryKeyField(Product, source="product")
    quantity = _quantity()
    unit_price = _money(min_value=Decimal(0), help_text="The price the till showed.")
    discount_amount = _money(required=False, default=Decimal(0), min_value=Decimal(0))
    price_override = serializers.BooleanField(
        required=False, default=False, help_text="The cashier changed the price on purpose."
    )
    override_reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    scanned_code = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )


class _TenderInput(serializers.Serializer[Any]):
    payment_method_id = ScopedPrimaryKeyField(PaymentMethod, source="payment_method")
    amount = _money()
    tendered = _money(required=False, allow_null=True, help_text="Cash handed over.")
    reference = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="", help_text="e.g. M-Pesa code"
    )


class SaleCreateSerializer(serializers.Serializer[Any]):
    client_txn_id = serializers.UUIDField()
    occurred_at = serializers.DateTimeField(required=False)
    customer_id = ScopedPrimaryKeyField(
        Customer, source="customer", required=False, allow_null=True, default=None
    )
    items = _ItemInput(many=True, allow_empty=False)
    order_discount = _money(required=False, default=Decimal(0), min_value=Decimal(0))
    tenders = _TenderInput(many=True, required=False, default=list)
    credit_amount = _money(required=False, default=Decimal(0), min_value=Decimal(0))
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


# --- Read ------------------------------------------------------------------------------------


class SaleItemSerializer(serializers.ModelSerializer[SaleItem]):
    product_id = serializers.UUIDField()

    class Meta:
        model = SaleItem
        fields = (
            "line_no",
            "product_id",
            "product_name",
            "sku",
            "unit_code",
            "quantity",
            "unit_price",
            "list_price",
            "price_overridden",
            "override_reason",
            "discount_amount",
            "order_discount_share",
            "tax_rate",
            "tax_name",
            "tax_amount",
            "line_total",
        )
        read_only_fields = fields


class SalePaymentSerializer(serializers.ModelSerializer[Payment]):
    method = serializers.CharField(source="payment_method.code")
    method_name = serializers.CharField(source="payment_method.name")
    kind = serializers.CharField(source="payment_method.kind")
    reference = serializers.CharField(source="external_reference")

    class Meta:
        model = Payment
        fields = ("method", "method_name", "kind", "amount", "tendered", "reference", "status")


class _PersonSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class SaleSerializer(serializers.ModelSerializer[Sale]):
    store = serializers.CharField(source="store.code")
    cashier = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    items = SaleItemSerializer(many=True)
    payments = SalePaymentSerializer(many=True)

    class Meta:
        model = Sale
        fields = (
            "id",
            "receipt_number",
            "client_txn_id",
            "status",
            "store",
            "currency",
            "tax_mode",
            "subtotal",
            "discount_total",
            "tax_total",
            "total",
            "amount_paid",
            "amount_on_credit",
            "change_given",
            "items",
            "payments",
            "customer",
            "cashier",
            "notes",
            "origin",
            "occurred_at",
            "recorded_at",
        )
        read_only_fields = fields

    @extend_schema_field(_PersonSerializer)
    def get_cashier(self, sale: Sale) -> dict[str, Any]:
        return {"id": str(sale.cashier_id), "name": sale.cashier.full_name}

    @extend_schema_field(_PersonSerializer(allow_null=True))
    def get_customer(self, sale: Sale) -> dict[str, Any] | None:
        if sale.customer is None:
            return None
        return {"id": str(sale.customer_id), "name": sale.customer.name}


class SaleListSerializer(serializers.ModelSerializer[Sale]):
    cashier = serializers.CharField(source="cashier.full_name")
    customer = serializers.CharField(source="customer.name", allow_null=True, default=None)
    item_count = serializers.IntegerField()
    methods = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = (
            "id",
            "receipt_number",
            "status",
            "currency",
            "total",
            "amount_on_credit",
            "item_count",
            "methods",
            "customer",
            "cashier",
            "occurred_at",
        )
        read_only_fields = fields

    def get_methods(self, sale: Sale) -> list[str]:
        return sorted({p.payment_method.name for p in sale.payments.all()})


# --- Receipt -------------------------------------------------------------------------------


class _ReceiptBusiness(serializers.Serializer[Any]):
    name = serializers.CharField()
    store_name = serializers.CharField()
    address = serializers.CharField()
    phone = serializers.CharField()
    timezone = serializers.CharField()


class _ReceiptTax(serializers.Serializer[Any]):
    name = serializers.CharField()
    rate = serializers.CharField()
    taxable_amount = serializers.CharField()
    tax_amount = serializers.CharField()


class _ReceiptAccount(serializers.Serializer[Any]):
    charged = serializers.CharField()
    balance_after = serializers.CharField()


class ReceiptSerializer(serializers.Serializer[Any]):
    """Everything a printed receipt shows, already formatted for the currency."""

    business = _ReceiptBusiness()
    sale = SaleSerializer()
    taxes = _ReceiptTax(many=True)
    account = _ReceiptAccount(allow_null=True, help_text="Credit sales: the customer's balance.")
    reprint = serializers.BooleanField()
