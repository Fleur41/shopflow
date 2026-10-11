"""The catalog: products and the lookups they reference (categories, brands,
units of measure, tax rates).

Like all master data, products and lookups are never deleted, only
deactivated, and carry a ``version`` for optimistic locking. Products and
their identifiers also carry a ``row_version`` from a global sequence, set by
a database trigger, so clients can fetch only what changed (sync pull cursor).
"""

from typing import Any, ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from apps.audit.models import AppendOnlyError
from apps.common.fields import MoneyField, QuantityField
from apps.common.ids import uuid7
from apps.organizations.master_data import MasterData
from apps.organizations.models import TenantManager, TenantModel

from .etims_codes import PACKAGING_UNITS, PRODUCT_TYPES, QUANTITY_UNITS, TAX_TYPE_CHOICES

unit_code_validator = RegexValidator(
    regex=r"^[A-Z0-9]{1,10}$", message="Use 1-10 capital letters or digits, e.g. PCS or KG."
)


class Category(MasterData):
    objects: ClassVar[TenantManager["Category"]]
    audit_name = "category"
    unique_fields: ClassVar[dict[str, str]] = {"catalog_category_name_unique": "name"}

    name = models.CharField(max_length=80)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )

    class Meta:
        verbose_name_plural = "categories"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # Sibling names are unique ignoring case, including among top-level categories.
            models.UniqueConstraint(
                models.F("organization"),
                models.F("parent"),
                Lower("name"),
                nulls_distinct=False,
                name="catalog_category_name_unique",
            ),
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("id")), name="catalog_category_not_own_parent"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Brand(MasterData):
    objects: ClassVar[TenantManager["Brand"]]
    audit_name = "brand"
    unique_fields: ClassVar[dict[str, str]] = {"catalog_brand_name_unique": "name"}

    name = models.CharField(max_length=80)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                models.F("organization"), Lower("name"), name="catalog_brand_name_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class UnitOfMeasure(MasterData):
    """How a product is counted. Fractional quantities need ``allows_fraction``."""

    objects: ClassVar[TenantManager["UnitOfMeasure"]]
    audit_name = "unit"
    unique_fields: ClassVar[dict[str, str]] = {"catalog_unit_code_unique": "code"}

    code = models.CharField(max_length=10, validators=[unit_code_validator])
    name = models.CharField(max_length=40)
    allows_fraction = models.BooleanField(
        default=False, help_text="Allow quantities like 0.5 (e.g. kilograms, litres)."
    )
    etims_quantity_unit = models.CharField(
        max_length=5,
        blank=True,
        choices=QUANTITY_UNITS,
        help_text="KRA eTIMS unit of quantity, e.g. KG or U (pieces). Needed for eTIMS.",
    )

    class Meta:
        verbose_name = "unit of measure"
        verbose_name_plural = "units of measure"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "code"], name="catalog_unit_code_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[A-Z0-9]{1,10}$"), name="catalog_unit_code_format"
            ),
        ]

    def __str__(self) -> str:
        return self.code


class TaxRate(MasterData):
    """A tax rate as a fraction (0.1600 is 16 %).

    The rate is fixed once created: to change it, create a new rate and move
    products to it, so past records keep meaning what they said.
    """

    objects: ClassVar[TenantManager["TaxRate"]]
    audit_name = "tax_rate"
    unique_fields: ClassVar[dict[str, str]] = {"catalog_tax_rate_name_unique": "name"}

    name = models.CharField(max_length=60)
    rate = models.DecimalField(max_digits=5, decimal_places=4)
    etims_tax_type = models.CharField(
        max_length=1,
        blank=True,
        choices=TAX_TYPE_CHOICES,
        help_text="KRA eTIMS tax type (A-E). Needed for eTIMS.",
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                models.F("organization"), Lower("name"), name="catalog_tax_rate_name_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0, rate__lt=1), name="catalog_tax_rate_range"
            ),
        ]

    def __str__(self) -> str:
        return self.name


# --- Products ---------------------------------------------------------------------------


class Product(MasterData):
    objects: ClassVar[TenantManager["Product"]]
    audit_name = "product"
    unique_fields: ClassVar[dict[str, str]] = {"catalog_product_sku_unique": "sku"}

    sku = models.CharField(
        max_length=40, help_text="Your code for the product. Generated if left empty."
    )
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    brand = models.ForeignKey(
        Brand, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    unit = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name="+")
    tax_rate = models.ForeignKey(TaxRate, on_delete=models.PROTECT, related_name="+")
    selling_price = MoneyField(help_text="In the business's base currency.")
    default_cost = MoneyField(null=True, blank=True)
    default_reorder_level = QuantityField(null=True, blank=True)
    track_inventory = models.BooleanField(
        default=True, help_text="Off for services and other items without stock."
    )
    # KRA eTIMS (docs/ETIMS.md). Required once the business switches eTIMS on.
    etims_product_type = models.CharField(max_length=1, choices=PRODUCT_TYPES, default="2")
    etims_item_class_code = models.CharField(
        max_length=10,
        blank=True,
        validators=[RegexValidator(r"^\d{1,10}$", "KRA item classification codes are digits.")],
        help_text="From KRA's item classification list.",
    )
    etims_packaging_unit = models.CharField(max_length=5, blank=True, choices=PACKAGING_UNITS)
    etims_item_code = models.CharField(
        max_length=20, blank=True, editable=False, help_text="Assigned when registered with KRA."
    )
    row_version = models.BigIntegerField(default=0, editable=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                models.F("organization"), Lower("sku"), name="catalog_product_sku_unique"
            ),
            models.UniqueConstraint(
                fields=["organization", "etims_item_code"],
                condition=~models.Q(etims_item_code=""),
                name="catalog_product_etims_item_code_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(selling_price__gte=0), name="catalog_product_price_not_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(default_cost__gte=0) | models.Q(default_cost__isnull=True),
                name="catalog_product_cost_not_negative",
            ),
            models.CheckConstraint(
                condition=~models.Q(etims_product_type="3") | models.Q(track_inventory=False),
                name="catalog_product_services_have_no_stock",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(OpClass("name", name="gin_trgm_ops"), name="catalog_product_name_trgm"),
            models.Index(fields=["organization", "category"], name="catalog_product_cat_idx"),
            models.Index(fields=["row_version"], name="catalog_product_row_ver_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class ProductIdentifier(TenantModel):
    """A code that finds a product at the till: a barcode, QR code or extra SKU.

    A pack barcode (a carton of 12) has ``pack_quantity`` 12, so scanning it
    adds 12 units. Each code maps to exactly one product per business.
    """

    class Kind(models.TextChoices):
        BARCODE = "BARCODE", "Barcode"
        QR = "QR", "QR code"
        ALIAS = "ALIAS", "Other code"

    objects: ClassVar[TenantManager["ProductIdentifier"]]
    audit_name = "product_identifier"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="identifiers")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BARCODE)
    value = models.CharField(max_length=64)
    pack_quantity = QuantityField(default=1)
    is_primary = models.BooleanField(default=False)
    row_version = models.BigIntegerField(default=0, editable=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "value"], name="catalog_identifier_value_unique"
            ),
            models.UniqueConstraint(
                fields=["product"],
                condition=models.Q(is_primary=True),
                name="catalog_identifier_one_primary",
            ),
            models.CheckConstraint(
                condition=models.Q(pack_quantity__gt=0), name="catalog_identifier_pack_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["BARCODE", "QR", "ALIAS"]),
                name="catalog_identifier_kind_valid",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["row_version"], name="catalog_identifier_row_ver_idx"),
        ]

    def __str__(self) -> str:
        return self.value


class ProductPriceHistory(models.Model):
    """Every selling-price change, append-only. Feeds price-history reports.

    ``store`` is set for store price overrides (2.4); empty for the product's
    own price. ``old_price`` is empty for the price a product was created with.
    """

    # The runtime database role gets no UPDATE/DELETE here (apps.common.db_grants).
    append_only = True

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    store = models.ForeignKey(
        "organizations.Store", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    old_price = MoneyField(null=True, blank=True)
    new_price = MoneyField()
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "product price history"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["product", "changed_at"], name="catalog_price_history_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.old_price} -> {self.new_price}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Price history cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise AppendOnlyError("Price history cannot be deleted.")
