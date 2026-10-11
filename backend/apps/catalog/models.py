"""Catalog master data: categories, brands, units of measure and tax rates.

Products (Phase 2.2) reference these. Like all master data they are never
deleted, only deactivated, and carry a ``version`` for optimistic locking
(docs/DATABASE.md §1).
"""

from typing import ClassVar

from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower

from apps.organizations.models import TenantManager, TenantModel

unit_code_validator = RegexValidator(
    regex=r"^[A-Z0-9]{1,10}$", message="Use 1-10 capital letters or digits, e.g. PCS or KG."
)


class CatalogEntry(TenantModel):
    """Common shape of the catalog lookups."""

    # ``entity_type`` in the audit log.
    audit_name: ClassVar[str]

    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True


class Category(CatalogEntry):
    objects: ClassVar[TenantManager["Category"]]
    audit_name = "category"

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


class Brand(CatalogEntry):
    objects: ClassVar[TenantManager["Brand"]]
    audit_name = "brand"

    name = models.CharField(max_length=80)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                models.F("organization"), Lower("name"), name="catalog_brand_name_unique"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class UnitOfMeasure(CatalogEntry):
    """How a product is counted. Fractional quantities need ``allows_fraction``."""

    objects: ClassVar[TenantManager["UnitOfMeasure"]]
    audit_name = "unit"

    code = models.CharField(max_length=10, validators=[unit_code_validator])
    name = models.CharField(max_length=40)
    allows_fraction = models.BooleanField(
        default=False, help_text="Allow quantities like 0.5 (e.g. kilograms, litres)."
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


class TaxRate(CatalogEntry):
    """A tax rate as a fraction (0.1600 is 16 %).

    The rate is fixed once created: to change it, create a new rate and move
    products to it, so past records keep meaning what they said.
    """

    objects: ClassVar[TenantManager["TaxRate"]]
    audit_name = "tax_rate"

    name = models.CharField(max_length=60)
    rate = models.DecimalField(max_digits=5, decimal_places=4)

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
