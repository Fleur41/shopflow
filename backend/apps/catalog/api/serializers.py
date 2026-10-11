from decimal import Decimal
from typing import Any, ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.organizations.api.master_data import (
    ENTRY_FIELDS,
    READ_ONLY_FIELDS,
    MasterDataSerializer,
    VersionedUpdateMixin,
)
from apps.organizations.api.serializers import ScopedPrimaryKeyField

from ..etims_codes import TAX_TYPES
from ..models import (
    Brand,
    Category,
    Product,
    ProductIdentifier,
    ProductPriceHistory,
    TaxRate,
    UnitOfMeasure,
    unit_code_validator,
)

# --- Categories ---------------------------------------------------------------------


class CategorySerializer(MasterDataSerializer[Category]):
    # The stubs confuse this with Field.parent; DRF's metaclass keeps declared fields apart.
    parent = ScopedPrimaryKeyField(Category, allow_null=True, required=False)  # type: ignore[assignment]
    taken_messages: ClassVar[dict[str, str]] = {
        "name": "Another category at this level already has this name."
    }

    class Meta:
        model = Category
        fields = ("id", "name", "parent", *ENTRY_FIELDS)
        read_only_fields = READ_ONLY_FIELDS

    def unique_scope(self, attrs: dict[str, Any]) -> dict[str, Any]:
        parent = attrs["parent"] if "parent" in attrs else getattr(self.instance, "parent", None)
        return {"parent": parent}

    def validate_parent(self, value: Category | None) -> Category | None:
        if value is not None and not value.is_active:
            raise serializers.ValidationError(
                "This category is deactivated. Choose an active one.", code="inactive"
            )
        return value


class CategoryUpdateSerializer(VersionedUpdateMixin, CategorySerializer):
    pass


# --- Brands -------------------------------------------------------------------------


class BrandSerializer(MasterDataSerializer[Brand]):
    taken_messages: ClassVar[dict[str, str]] = {"name": "Another brand already has this name."}

    class Meta:
        model = Brand
        fields = ("id", "name", *ENTRY_FIELDS)
        read_only_fields = READ_ONLY_FIELDS


class BrandUpdateSerializer(VersionedUpdateMixin, BrandSerializer):
    pass


# --- Units of measure -------------------------------------------------------------------


class UnitSerializer(MasterDataSerializer[UnitOfMeasure]):
    # Declared explicitly so input is upper-cased before the format check runs.
    code = serializers.CharField(max_length=20)
    unique_fields = ("code",)
    taken_messages: ClassVar[dict[str, str]] = {"code": "Another unit already uses this code."}

    class Meta:
        model = UnitOfMeasure
        fields = ("id", "code", "name", "allows_fraction", "etims_quantity_unit", *ENTRY_FIELDS)
        read_only_fields = READ_ONLY_FIELDS

    def validate_code(self, value: str) -> str:
        code = value.strip().upper()
        try:
            unit_code_validator(code)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages), code="invalid") from exc
        return code


class UnitUpdateSerializer(VersionedUpdateMixin, UnitSerializer):
    pass


# --- Tax rates -------------------------------------------------------------------------------


class TaxRateSerializer(MasterDataSerializer[TaxRate]):
    rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=Decimal(0),
        max_value=Decimal("0.9999"),
        help_text="A fraction: 0.16 is 16 %. Fixed once created.",
    )
    taken_messages: ClassVar[dict[str, str]] = {"name": "Another tax rate already has this name."}

    class Meta:
        model = TaxRate
        fields = ("id", "name", "rate", "etims_tax_type", *ENTRY_FIELDS)
        read_only_fields = READ_ONLY_FIELDS

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        tax_type = attrs.get("etims_tax_type")
        rate = attrs.get("rate", getattr(self.instance, "rate", None))
        if tax_type and rate is not None and TAX_TYPES[tax_type][1] != rate:
            label, expected = TAX_TYPES[tax_type]
            raise serializers.ValidationError(
                {"etims_tax_type": [f"{label} is for a rate of {expected:.2%}."]}, code="mismatch"
            )
        return attrs


class TaxRateUpdateSerializer(VersionedUpdateMixin, TaxRateSerializer):
    # Past sales keep the rate they were taxed at: to change a rate, create a
    # new one and move products to it.
    rate = serializers.DecimalField(max_digits=5, decimal_places=4, read_only=True)


# --- Products --------------------------------------------------------------------------------


def gtin_check_digit_ok(digits: str) -> bool:
    """EAN-8, UPC-A, EAN-13 and GTIN-14 end in a check digit (mod 10, weights 3/1)."""
    *body, check = (int(d) for d in digits)
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


class ProductIdentifierSerializer(serializers.ModelSerializer[ProductIdentifier]):
    pack_quantity = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        help_text="Units added per scan: 12 for a carton barcode. Default 1.",
    )

    class Meta:
        model = ProductIdentifier
        fields = ("id", "kind", "value", "pack_quantity", "is_primary")
        read_only_fields = ("id",)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        value = attrs["value"] = attrs["value"].strip()
        kind = attrs.get("kind", ProductIdentifier.Kind.BARCODE)
        if not value:
            raise serializers.ValidationError({"value": ["Enter a code."]}, code="blank")
        if (
            kind == ProductIdentifier.Kind.BARCODE
            and value.isdigit()
            and len(value) in (8, 12, 13, 14)
            and not gtin_check_digit_ok(value)
        ):
            raise serializers.ValidationError(
                {"value": ["This barcode's check digit is wrong. Check for a typing mistake."]},
                code="check_digit",
            )
        return attrs


class _ActiveField(ScopedPrimaryKeyField):
    """A related lookup that must be active to be newly assigned."""

    def to_internal_value(self, data: Any) -> Any:
        entry = super().to_internal_value(data)
        instance = getattr(self.parent, "instance", None)
        unchanged = instance is not None and getattr(instance, self.field_name or "") == entry
        if not entry.is_active and not unchanged:
            raise serializers.ValidationError(
                "This is deactivated. Choose an active one.", code="inactive"
            )
        return entry


class ProductSerializer(MasterDataSerializer[Product]):
    sku = serializers.CharField(max_length=40, required=False, allow_blank=True)
    category = _ActiveField(Category, allow_null=True, required=False)
    brand = _ActiveField(Brand, allow_null=True, required=False)
    unit = _ActiveField(UnitOfMeasure)
    tax_rate = _ActiveField(TaxRate)
    selling_price = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=Decimal(0))
    default_cost = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=Decimal(0), required=False, allow_null=True
    )
    identifiers = ProductIdentifierSerializer(
        many=True, required=False, help_text="Barcodes and other codes. On create only."
    )
    unique_fields = ("sku",)
    taken_messages: ClassVar[dict[str, str]] = {"sku": "Another product already uses this SKU."}

    class Meta:
        model = Product
        fields = (
            "id",
            "sku",
            "name",
            "category",
            "brand",
            "unit",
            "tax_rate",
            "selling_price",
            "default_cost",
            "default_reorder_level",
            "track_inventory",
            "etims_product_type",
            "etims_item_class_code",
            "etims_packaging_unit",
            "etims_item_code",
            "identifiers",
            "row_version",
            *ENTRY_FIELDS,
        )
        read_only_fields = (*READ_ONLY_FIELDS, "etims_item_code", "row_version")

    def validate_sku(self, value: str) -> str:
        return value.strip()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        product_type = attrs.get(
            "etims_product_type", getattr(self.instance, "etims_product_type", "2")
        )
        if product_type == "3":  # a service has no stock
            if attrs.get("track_inventory") is True:
                raise serializers.ValidationError(
                    {"track_inventory": ["Services don't have stock."]}, code="service"
                )
            attrs["track_inventory"] = False
        return attrs


class ProductUpdateSerializer(VersionedUpdateMixin, ProductSerializer):
    identifiers = ProductIdentifierSerializer(many=True, read_only=True)


class PriceHistorySerializer(serializers.ModelSerializer[ProductPriceHistory]):
    changed_by = serializers.CharField(source="changed_by.full_name", read_only=True, default=None)

    class Meta:
        model = ProductPriceHistory
        fields = ("id", "store", "old_price", "new_price", "changed_by", "changed_at")
