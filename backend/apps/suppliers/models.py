"""Suppliers, their contacts, and which products they supply (docs/DATABASE.md §2.5).

What a business owes a supplier (accounts, ledger, payments) arrives with
purchasing in Phase 5.
"""

from typing import ClassVar

from django.db import models
from django.db.models.functions import Lower

from apps.catalog.models import Product
from apps.common.fields import MoneyField, QuantityField
from apps.organizations.master_data import MasterData
from apps.organizations.models import TenantManager, TenantModel


class Supplier(MasterData):
    objects: ClassVar[TenantManager["Supplier"]]
    audit_name = "supplier"
    unique_fields: ClassVar[dict[str, str]] = {
        "suppliers_supplier_code_unique": "code",
        "suppliers_supplier_name_unique": "name",
    }

    code = models.CharField(max_length=20, help_text="Generated if left empty (S00001, …).")
    name = models.CharField(max_length=120)
    kra_pin = models.CharField(
        max_length=11, blank=True, help_text="Matches eTIMS purchase invoices to this supplier."
    )
    phone = models.CharField(max_length=16, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=300, blank=True)
    payment_terms_days = models.PositiveSmallIntegerField(
        default=0, help_text="Days to pay an invoice; 0 means on delivery."
    )
    notes = models.TextField(blank=True, max_length=2000)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                models.F("organization"), Lower("code"), name="suppliers_supplier_code_unique"
            ),
            models.UniqueConstraint(
                models.F("organization"), Lower("name"), name="suppliers_supplier_name_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(kra_pin="") | models.Q(kra_pin__regex=r"^[AP][0-9]{9}[A-Z]$"),
                name="suppliers_supplier_kra_pin_format",
            ),
            models.CheckConstraint(
                condition=models.Q(payment_terms_days__lte=365),
                name="suppliers_supplier_terms_max_year",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class SupplierContact(TenantModel):
    """A person at a supplier. Contacts are plain address-book entries: removing
    one is allowed (and audited)."""

    objects: ClassVar[TenantManager["SupplierContact"]]

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="contacts")
    name = models.CharField(max_length=120)
    role_title = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=16, blank=True)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["supplier"],
                condition=models.Q(is_primary=True),
                name="suppliers_contact_one_primary",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ProductSupplier(TenantModel):
    """A product a supplier supplies, with how to order it from them.

    At most one supplier per product is preferred: reorder suggestions and
    purchase orders (Phase 5) start from it.
    """

    objects: ClassVar[TenantManager["ProductSupplier"]]

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="+")
    supplier_sku = models.CharField(
        max_length=40, blank=True, help_text="The supplier's own code for the product."
    )
    min_order_qty = QuantityField(null=True, blank=True)
    lead_time_days = models.PositiveSmallIntegerField(null=True, blank=True)
    is_preferred = models.BooleanField(default=False)
    last_purchase_price = MoneyField(
        null=True, blank=True, editable=False, help_text="Updated by goods receipts (Phase 5)."
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["product", "supplier"], name="suppliers_link_unique"),
            models.UniqueConstraint(
                fields=["product"],
                condition=models.Q(is_preferred=True),
                name="suppliers_link_one_preferred",
            ),
            models.CheckConstraint(
                condition=models.Q(min_order_qty__isnull=True) | models.Q(min_order_qty__gt=0),
                name="suppliers_link_moq_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(lead_time_days__isnull=True) | models.Q(lead_time_days__lte=365),
                name="suppliers_link_lead_time_max_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supplier_id} → {self.product_id}"
