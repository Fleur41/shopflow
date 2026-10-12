from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog import images
from apps.catalog.models import Product
from apps.organizations.api.serializers import ScopedPrimaryKeyField

from ..models import InventoryMovement, StockAdjustment, StockAdjustmentLine

MAX_LINES = 500


def _quantity(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=3, **kwargs)


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=19, decimal_places=4, **kwargs)


class _UnitSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()
    allows_fraction = serializers.BooleanField()


class _ProductRefSerializer(serializers.Serializer[Product]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    sku = serializers.CharField()


# --- Stock levels ---------------------------------------------------------------------


class StockRowSerializer(serializers.Serializer[Product]):
    """A stocked product with its level and settings in one store."""

    product_id = serializers.UUIDField(source="pk")
    name = serializers.CharField()
    sku = serializers.CharField()
    unit = _UnitSerializer()
    category = serializers.CharField(source="category.name", allow_null=True, default=None)
    thumbnail_url = serializers.SerializerMethodField()
    is_active = serializers.BooleanField()
    selling_price = _money()
    selling_price_override = _money(allow_null=True)
    price = serializers.SerializerMethodField(help_text="What it sells for in this store.")
    quantity_on_hand = _quantity()
    reorder_level = _quantity(
        source="store_reorder_level", allow_null=True, help_text="This store's own level."
    )
    effective_reorder_level = _quantity(
        allow_null=True, help_text="The store's level, or the product's default."
    )
    min_stock = _quantity(allow_null=True)
    max_stock = _quantity(allow_null=True)
    average_cost = _money(allow_null=True)
    allow_negative = serializers.BooleanField()
    stock_status = serializers.ChoiceField(choices=["out", "low", "ok"])
    version = serializers.IntegerField(source="level_version")

    def get_thumbnail_url(self, product: Product) -> str | None:
        return images.url_for(product.thumbnail_key)

    def get_price(self, product: Any) -> str:
        price = product.selling_price_override
        if price is None:
            price = product.selling_price
        return f"{price:.4f}"


class StockSettingsUpdateSerializer(serializers.Serializer[Any]):
    version = serializers.IntegerField(
        help_text="The version you last read; the update is refused if someone changed it since."
    )
    reorder_level = _quantity(required=False, allow_null=True, min_value=Decimal(0))
    min_stock = _quantity(required=False, allow_null=True, min_value=Decimal(0))
    max_stock = _quantity(required=False, allow_null=True, min_value=Decimal(0))
    selling_price_override = _money(required=False, allow_null=True, min_value=Decimal(0))
    allow_negative = serializers.BooleanField(required=False)


# --- Lookup ---------------------------------------------------------------------------


class LookupSerializer(serializers.Serializer[Any]):
    product_id = serializers.UUIDField()
    name = serializers.CharField()
    sku = serializers.CharField()
    unit = _UnitSerializer()
    tax_rate = serializers.CharField(help_text='e.g. "0.1600"')
    price = _money(help_text="What it sells for in this store.")
    pack_quantity = _quantity(help_text="How many units the scanned code stands for.")
    track_inventory = serializers.BooleanField()
    quantity_on_hand = _quantity(allow_null=True, help_text="Empty for items without stock.")
    is_active = serializers.BooleanField()
    thumbnail_url = serializers.CharField(allow_null=True)


# --- Movements --------------------------------------------------------------------------


class _DocumentSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=["adjustment", "sale"])
    id = serializers.UUIDField()
    reason_code = serializers.CharField(required=False)
    note = serializers.CharField(required=False)
    receipt_number = serializers.CharField(required=False)


class MovementSerializer(serializers.ModelSerializer[InventoryMovement]):
    product = _ProductRefSerializer()
    performed_by = serializers.CharField(source="performed_by.full_name")
    document = serializers.SerializerMethodField(help_text="What caused the movement.")

    class Meta:
        model = InventoryMovement
        fields = (
            "id",
            "product",
            "movement_type",
            "quantity",
            "quantity_before",
            "quantity_after",
            "unit_cost",
            "seq",
            "performed_by",
            "occurred_at",
            "recorded_at",
            "document",
        )
        read_only_fields = fields

    @extend_schema_field(_DocumentSerializer(allow_null=True))
    def get_document(self, movement: InventoryMovement) -> dict[str, Any] | None:
        line = movement.adjustment_line
        if line is not None:
            return {
                "kind": "adjustment",
                "id": str(line.adjustment_id),
                "reason_code": line.adjustment.reason_code,
                "note": line.adjustment.note,
            }
        sale_item = getattr(movement, "sale_item", None)
        if sale_item is not None:
            return {
                "kind": "sale",
                "id": str(sale_item.sale_id),
                "receipt_number": sale_item.sale.receipt_number,
            }
        return None


# --- Adjustments --------------------------------------------------------------------------


class _AdjustmentLineInput(serializers.Serializer[Any]):
    product_id = ScopedPrimaryKeyField(Product, source="product")
    quantity_delta = _quantity(required=False, allow_null=True)
    counted_quantity = _quantity(required=False, allow_null=True, min_value=Decimal(0))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        given = [f for f in ("quantity_delta", "counted_quantity") if attrs.get(f) is not None]
        if len(given) != 1:
            raise serializers.ValidationError(
                "Give either the change (quantity_delta) or what you counted (counted_quantity).",
                code="one_of",
            )
        if attrs.get("quantity_delta") == 0:
            raise serializers.ValidationError({"quantity_delta": ["Enter a change other than 0."]})
        return attrs


def _distinct_products(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not lines:
        raise serializers.ValidationError("Add at least one product.", code="empty")
    if len(lines) > MAX_LINES:
        raise serializers.ValidationError(f"At most {MAX_LINES} products at a time.")
    seen = set()
    for line in lines:
        product = line["product"]
        if not product.track_inventory:
            raise serializers.ValidationError(f"{product.name} is not a stocked item.")
        if product.pk in seen:
            raise serializers.ValidationError(f"{product.name} is listed twice.", code="duplicate")
        seen.add(product.pk)
    return lines


class AdjustmentCreateSerializer(serializers.Serializer[Any]):
    client_txn_id = serializers.UUIDField()
    reason_code = serializers.ChoiceField(
        choices=[r for r in StockAdjustment.Reason.choices if r[0] != "OPENING_BALANCE"]
    )
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    occurred_at = serializers.DateTimeField(required=False)
    lines = _AdjustmentLineInput(many=True)

    def validate_lines(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _distinct_products(lines)


class _OpeningLineInput(serializers.Serializer[Any]):
    product_id = ScopedPrimaryKeyField(Product, source="product")
    quantity = _quantity(min_value=Decimal(0))
    unit_cost = _money(required=False, allow_null=True, min_value=Decimal(0))


class OpeningBalanceSerializer(serializers.Serializer[Any]):
    client_txn_id = serializers.UUIDField()
    occurred_at = serializers.DateTimeField(required=False)
    lines = _OpeningLineInput(many=True)

    def validate_lines(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _distinct_products(lines)


class AdjustmentLineSerializer(serializers.ModelSerializer[StockAdjustmentLine]):
    product = _ProductRefSerializer()

    class Meta:
        model = StockAdjustmentLine
        fields = ("product", "quantity_delta", "counted_quantity")
        read_only_fields = fields


class AdjustmentSerializer(serializers.ModelSerializer[StockAdjustment]):
    created_by = serializers.CharField(source="created_by.full_name")
    lines = AdjustmentLineSerializer(many=True)

    class Meta:
        model = StockAdjustment
        fields = (
            "id",
            "client_txn_id",
            "reason_code",
            "note",
            "created_by",
            "occurred_at",
            "created_at",
            "lines",
        )
        read_only_fields = fields
