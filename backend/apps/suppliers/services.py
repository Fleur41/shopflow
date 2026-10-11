"""Supplier use cases. Every change is audited in the same transaction.

Generic create/update of suppliers lives in ``master_data``; this module adds
generated codes, contacts (one primary per supplier) and product links (at
most one preferred supplier per product).
"""

from typing import Any

from django.db import IntegrityError, transaction
from rest_framework import status

from apps.audit.services import diff, record_audit
from apps.catalog.models import Product
from apps.common.errors import ApplicationError
from apps.organizations import master_data
from apps.organizations.context import RequestContext

from .models import ProductSupplier, Supplier, SupplierContact

GENERATED_CODE_PREFIX = "S"


class LinkRefused(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"
    title = "Invalid request"


# --- Suppliers ------------------------------------------------------------------------


def create_supplier(ctx: RequestContext, **fields: Any) -> Supplier:
    with transaction.atomic():
        if not fields.get("code"):
            fields["code"] = master_data.next_code(
                ctx, Supplier, field="code", prefix=GENERATED_CODE_PREFIX, width=5
            )
        return master_data.create_entry(ctx, Supplier, **fields)


# --- Contacts -------------------------------------------------------------------------


def add_contact(ctx: RequestContext, supplier: Supplier, **fields: Any) -> SupplierContact:
    with transaction.atomic():
        _lock(ctx, supplier)
        contacts = SupplierContact.objects.for_org(ctx.organization).filter(supplier=supplier)
        if not contacts.exists():
            fields["is_primary"] = True  # the first contact is the one to call
        elif fields.get("is_primary"):
            contacts.filter(is_primary=True).update(is_primary=False)
        contact = SupplierContact.objects.create(
            organization=ctx.organization, supplier=supplier, **fields
        )
        _audit(ctx, supplier, "supplier.contact_added", {"contact": [None, contact.name]})
    return contact


def update_contact(
    ctx: RequestContext, contact: SupplierContact, **changes: Any
) -> SupplierContact:
    with transaction.atomic():
        _lock(ctx, contact.supplier)
        contact.refresh_from_db()
        if changes.get("is_primary") and not contact.is_primary:
            SupplierContact.objects.for_org(ctx.organization).filter(
                supplier_id=contact.supplier_id, is_primary=True
            ).update(is_primary=False)
        elif changes.get("is_primary") is False and contact.is_primary:
            changes.pop("is_primary")  # a supplier keeps a primary contact; choose another instead
        before = master_data.audit_values(contact, changes)
        for field, value in changes.items():
            setattr(contact, field, value)
        changed = diff(before, master_data.audit_values(contact, changes))
        if changed:
            contact.save()
            _audit(ctx, contact.supplier, "supplier.contact_updated", changed)
    return contact


def remove_contact(ctx: RequestContext, contact: SupplierContact) -> None:
    with transaction.atomic():
        _lock(ctx, contact.supplier)
        contact.delete()
        if contact.is_primary:
            successor = (
                SupplierContact.objects.for_org(ctx.organization)
                .filter(supplier_id=contact.supplier_id)
                .order_by("id")
                .first()
            )
            if successor is not None:
                successor.is_primary = True
                successor.save(update_fields=["is_primary"])
        _audit(ctx, contact.supplier, "supplier.contact_removed", {"contact": [contact.name, None]})


# --- Product links --------------------------------------------------------------------


def link_product(
    ctx: RequestContext, *, product: Product, supplier: Supplier, **fields: Any
) -> ProductSupplier:
    if not supplier.is_active:
        raise LinkRefused(
            "One or more fields are invalid.",
            errors=[
                {
                    "pointer": "/supplier",
                    "code": "INACTIVE",
                    "detail": "This supplier is deactivated.",
                }
            ],
        )
    with transaction.atomic():
        _lock_product(ctx, product)
        links = ProductSupplier.objects.for_org(ctx.organization).filter(product=product)
        if links.filter(supplier=supplier).exists():
            raise _already_linked()
        if fields.get("is_preferred"):
            links.filter(is_preferred=True).update(is_preferred=False)
        elif not links.exists():
            fields["is_preferred"] = True  # a product's only supplier is its preferred one
        try:
            with transaction.atomic():
                link = ProductSupplier.objects.create(
                    organization=ctx.organization, product=product, supplier=supplier, **fields
                )
        except IntegrityError as exc:  # linked by another request just now
            raise _already_linked() from exc
        _audit(ctx, supplier, "supplier.product_linked", {"product": [None, str(product.pk)]})
    return link


def update_link(ctx: RequestContext, link: ProductSupplier, **changes: Any) -> ProductSupplier:
    with transaction.atomic():
        _lock_product(ctx, link.product)
        link.refresh_from_db()
        if changes.get("is_preferred") and not link.is_preferred:
            ProductSupplier.objects.for_org(ctx.organization).filter(
                product_id=link.product_id, is_preferred=True
            ).update(is_preferred=False)
        before = master_data.audit_values(link, changes)
        for field, value in changes.items():
            setattr(link, field, value)
        changed = diff(before, master_data.audit_values(link, changes))
        if changed:
            link.save()
            product = str(link.product_id)  # which link, in the usual [before, after] shape
            _audit(
                ctx,
                link.supplier,
                "supplier.product_link_updated",
                {"product": [product, product], **changed},
            )
    return link


def unlink_product(ctx: RequestContext, link: ProductSupplier) -> None:
    with transaction.atomic():
        _lock_product(ctx, link.product)
        link.delete()
        _audit(
            ctx,
            link.supplier,
            "supplier.product_unlinked",
            {"product": [str(link.product_id), None]},
        )


# --- Helpers --------------------------------------------------------------------------


def _lock(ctx: RequestContext, supplier: Supplier) -> None:
    """Serialize changes to one supplier's contacts."""
    Supplier.objects.for_org(ctx.organization).select_for_update().get(pk=supplier.pk)


def _lock_product(ctx: RequestContext, product: Product) -> None:
    """Serialize changes to one product's supplier links ("preferred" can't race)."""
    Product.objects.for_org(ctx.organization).select_for_update().get(pk=product.pk)


def _audit(ctx: RequestContext, supplier: Supplier, action: str, changes: dict[str, Any]) -> None:
    record_audit(
        ctx.audit_actor,
        action=action,
        entity_type=Supplier.audit_name,
        entity_id=supplier.pk,
        changes=changes,
    )


def _already_linked() -> LinkRefused:
    return LinkRefused(
        "One or more fields are invalid.",
        errors=[
            {
                "pointer": "/supplier",
                "code": "ALREADY_LINKED",
                "detail": "This supplier is already linked to this product.",
            }
        ],
    )
