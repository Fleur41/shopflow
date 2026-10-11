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

from ..models import Brand, Category, TaxRate, UnitOfMeasure, unit_code_validator

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
        fields = ("id", "code", "name", "allows_fraction", *ENTRY_FIELDS)
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
        fields = ("id", "name", "rate", *ENTRY_FIELDS)
        read_only_fields = READ_ONLY_FIELDS


class TaxRateUpdateSerializer(VersionedUpdateMixin, TaxRateSerializer):
    # Past sales keep the rate they were taxed at: to change a rate, create a
    # new one and move products to it.
    rate = serializers.DecimalField(max_digits=5, decimal_places=4, read_only=True)
