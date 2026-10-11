from decimal import Decimal
from typing import Any, ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.catalog.models import Product
from apps.common.validators import normalize_kra_pin, normalize_phone
from apps.organizations.api.master_data import (
    ENTRY_FIELDS,
    READ_ONLY_FIELDS,
    MasterDataSerializer,
    VersionedUpdateMixin,
)
from apps.organizations.api.serializers import ScopedPrimaryKeyField

from ..models import ProductSupplier, Supplier, SupplierContact


def _django_validated(normalize: Any, value: str) -> str:
    try:
        result: str = normalize(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages), code="invalid") from exc
    return result


class _ContactFields(serializers.Serializer[Any]):
    def validate_phone(self, value: str) -> str:
        return _django_validated(normalize_phone, value)


class SupplierSerializer(_ContactFields, MasterDataSerializer[Supplier]):
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    unique_fields = ("code", "name")
    taken_messages: ClassVar[dict[str, str]] = {
        "code": "Another supplier already uses this code.",
        "name": "Another supplier already has this name.",
    }

    class Meta:
        model = Supplier
        fields = (
            "id",
            "code",
            "name",
            "kra_pin",
            "phone",
            "email",
            "address",
            "payment_terms_days",
            "notes",
            *ENTRY_FIELDS,
        )
        read_only_fields = READ_ONLY_FIELDS
        extra_kwargs: ClassVar[dict[str, Any]] = {"payment_terms_days": {"max_value": 365}}

    def validate_code(self, value: str) -> str:
        return value.strip().upper()

    def validate_kra_pin(self, value: str) -> str:
        return _django_validated(normalize_kra_pin, value)


class SupplierUpdateSerializer(VersionedUpdateMixin, SupplierSerializer):
    code = serializers.CharField(read_only=True)  # used in reports and documents


class SupplierContactSerializer(_ContactFields, serializers.ModelSerializer[SupplierContact]):
    class Meta:
        model = SupplierContact
        fields = ("id", "name", "role_title", "phone", "email", "is_primary")
        read_only_fields = ("id",)


class ProductSupplierSerializer(serializers.ModelSerializer[ProductSupplier]):
    product = ScopedPrimaryKeyField(Product)
    supplier = ScopedPrimaryKeyField(Supplier)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    min_order_qty = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=Decimal("0.001"), required=False, allow_null=True
    )

    class Meta:
        model = ProductSupplier
        fields = (
            "id",
            "product",
            "product_name",
            "product_sku",
            "supplier",
            "supplier_name",
            "supplier_sku",
            "min_order_qty",
            "lead_time_days",
            "is_preferred",
            "last_purchase_price",
        )
        read_only_fields = ("id", "last_purchase_price")
        extra_kwargs: ClassVar[dict[str, Any]] = {"lead_time_days": {"max_value": 365}}
        # The service checks "already linked" under a lock, with a clearer message.
        validators: ClassVar[list[Any]] = []


class LinkFromSupplierSerializer(ProductSupplierSerializer):
    """POST /suppliers/{id}/products/: the supplier comes from the URL."""

    supplier = serializers.PrimaryKeyRelatedField(read_only=True)  # type: ignore[assignment,var-annotated]


class LinkFromProductSerializer(ProductSupplierSerializer):
    """POST /products/{id}/suppliers/: the product comes from the URL."""

    product = serializers.PrimaryKeyRelatedField(read_only=True)  # type: ignore[assignment,var-annotated]


class ProductSupplierUpdateSerializer(ProductSupplierSerializer):
    """Which product and supplier a link joins is fixed; unlink and link again instead."""

    product = serializers.PrimaryKeyRelatedField(read_only=True)  # type: ignore[assignment,var-annotated]
    supplier = serializers.PrimaryKeyRelatedField(read_only=True)  # type: ignore[assignment,var-annotated]
