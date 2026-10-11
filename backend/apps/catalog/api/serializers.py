from decimal import Decimal
from typing import Any, ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.organizations.api.serializers import ScopedPrimaryKeyField, _ctx

from ..models import Brand, CatalogEntry, Category, TaxRate, UnitOfMeasure, unit_code_validator

_ENTRY_FIELDS = ("is_active", "version", "created_at", "updated_at")
_READ_ONLY = ("id", "version", "created_at", "updated_at")


class _EntrySerializer[E: CatalogEntry](serializers.ModelSerializer[E]):
    """Rejects a name (or code) another entry in the same scope already uses,
    ignoring case, so "Soda" and "soda" can't both exist."""

    unique_field: ClassVar[str] = "name"
    taken_message: ClassVar[str] = "This name is already in use."

    def unique_scope(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return {}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        field = self.unique_field
        value = attrs.get(field, getattr(self.instance, field, None))
        model: type[CatalogEntry] = self.Meta.model
        clashes = model.objects.for_org(_ctx(self).organization).filter(
            **{f"{field}__iexact": value}, **self.unique_scope(attrs)
        )
        if self.instance is not None:
            clashes = clashes.exclude(pk=self.instance.pk)
        if clashes.exists():
            raise serializers.ValidationError({field: [self.taken_message]}, code="taken")
        return attrs


class _UpdateMixin(serializers.Serializer[Any]):
    version = serializers.IntegerField(
        help_text="The version you last read; the update is refused if someone changed it since."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Updates are partial, which makes DRF skip required checks.
        if "version" not in attrs:
            raise serializers.ValidationError(
                {"version": ["This field is required."]}, code="required"
            )
        validated: dict[str, Any] = super().validate(attrs)
        return validated


# --- Categories ---------------------------------------------------------------------


class CategorySerializer(_EntrySerializer[Category]):
    # The stubs confuse this with Field.parent; DRF's metaclass keeps declared fields apart.
    parent = ScopedPrimaryKeyField(Category, allow_null=True, required=False)  # type: ignore[assignment]
    taken_message = "Another category at this level already has this name."

    class Meta:
        model = Category
        fields = ("id", "name", "parent", *_ENTRY_FIELDS)
        read_only_fields = _READ_ONLY

    def unique_scope(self, attrs: dict[str, Any]) -> dict[str, Any]:
        parent = attrs["parent"] if "parent" in attrs else getattr(self.instance, "parent", None)
        return {"parent": parent}

    def validate_parent(self, value: Category | None) -> Category | None:
        if value is not None and not value.is_active:
            raise serializers.ValidationError(
                "This category is deactivated. Choose an active one.", code="inactive"
            )
        return value


class CategoryUpdateSerializer(_UpdateMixin, CategorySerializer):
    pass


# --- Brands -------------------------------------------------------------------------


class BrandSerializer(_EntrySerializer[Brand]):
    taken_message = "Another brand already has this name."

    class Meta:
        model = Brand
        fields = ("id", "name", *_ENTRY_FIELDS)
        read_only_fields = _READ_ONLY


class BrandUpdateSerializer(_UpdateMixin, BrandSerializer):
    pass


# --- Units of measure -------------------------------------------------------------------


class UnitSerializer(_EntrySerializer[UnitOfMeasure]):
    # Declared explicitly so input is upper-cased before the format check runs.
    code = serializers.CharField(max_length=20)
    unique_field = "code"
    taken_message = "Another unit already uses this code."

    class Meta:
        model = UnitOfMeasure
        fields = ("id", "code", "name", "allows_fraction", *_ENTRY_FIELDS)
        read_only_fields = _READ_ONLY

    def validate_code(self, value: str) -> str:
        code = value.strip().upper()
        try:
            unit_code_validator(code)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages), code="invalid") from exc
        return code


class UnitUpdateSerializer(_UpdateMixin, UnitSerializer):
    pass


# --- Tax rates -------------------------------------------------------------------------------


class TaxRateSerializer(_EntrySerializer[TaxRate]):
    rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        min_value=Decimal(0),
        max_value=Decimal("0.9999"),
        help_text="A fraction: 0.16 is 16 %. Fixed once created.",
    )
    taken_message = "Another tax rate already has this name."

    class Meta:
        model = TaxRate
        fields = ("id", "name", "rate", *_ENTRY_FIELDS)
        read_only_fields = _READ_ONLY


class TaxRateUpdateSerializer(_UpdateMixin, TaxRateSerializer):
    # Past sales keep the rate they were taxed at: to change a rate, create a
    # new one and move products to it.
    rate = serializers.DecimalField(max_digits=5, decimal_places=4, read_only=True)
