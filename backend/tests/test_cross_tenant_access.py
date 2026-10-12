"""BOLA/IDOR suite (docs/SECURITY.md §4).

Business B's owner, who holds every permission in B, calls every endpoint
that takes an ID, for every method, using business A's IDs. Each call must
return 404, and nothing in A may change. New endpoints with path parameters
fail here until they are registered in TARGETS.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.accounts.models import AuthSession
from apps.audit.models import AuditLog
from apps.cash import services as cash_services
from apps.cash.models import CashMovement, CashSession, Till
from apps.catalog.models import (
    Brand,
    Category,
    Product,
    ProductIdentifier,
    TaxRate,
    UnitOfMeasure,
)
from apps.customers import services as customer_services
from apps.customers.models import Customer, CustomerAccount, CustomerLedgerEntry
from apps.inventory import services as inventory_services
from apps.inventory.models import InventoryMovement, StockAdjustment, StockLevel
from apps.organizations.models import Invitation, Membership, Role, Store
from apps.organizations.testing import (
    add_staff,
    add_store,
    client_for,
    context_for,
    create_business,
    role,
)
from apps.payments.models import Payment, PaymentMethod
from apps.sales import services as sale_services
from apps.sales.models import Sale
from apps.suppliers.models import ProductSupplier, Supplier, SupplierContact

from .routes import api_routes

pytestmark = pytest.mark.django_db

# Path template → how to fill it with business A's objects.
TARGETS = {
    "api/v1/stores/<uuid:store_id>/": lambda a: {"store_id": a.store.pk},
    "api/v1/roles/<uuid:role_id>/": lambda a: {"role_id": a.cashier_role.pk},
    "api/v1/members/<uuid:member_id>/": lambda a: {"member_id": a.cashier.pk},
    "api/v1/members/<uuid:member_id>/suspend/": lambda a: {"member_id": a.cashier.pk},
    "api/v1/members/<uuid:member_id>/reactivate/": lambda a: {"member_id": a.cashier.pk},
    "api/v1/auth/sessions/<uuid:session_id>/": lambda a: {"session_id": a.session.pk},
    "api/v1/invitations/<uuid:invitation_id>/revoke/": lambda a: {"invitation_id": a.invitation.pk},
    "api/v1/categories/<uuid:entry_id>/": lambda a: {"entry_id": a.category.pk},
    "api/v1/brands/<uuid:entry_id>/": lambda a: {"entry_id": a.brand.pk},
    "api/v1/units/<uuid:entry_id>/": lambda a: {"entry_id": a.unit.pk},
    "api/v1/tax-rates/<uuid:entry_id>/": lambda a: {"entry_id": a.tax_rate.pk},
    "api/v1/payment-methods/<uuid:entry_id>/": lambda a: {"entry_id": a.payment_method.pk},
    "api/v1/products/<uuid:entry_id>/": lambda a: {"entry_id": a.product.pk},
    "api/v1/products/<uuid:product_id>/identifiers/": lambda a: {"product_id": a.product.pk},
    "api/v1/products/<uuid:product_id>/identifiers/<uuid:identifier_id>/": lambda a: {
        "product_id": a.product.pk,
        "identifier_id": a.identifier.pk,
    },
    "api/v1/products/<uuid:product_id>/price-history/": lambda a: {"product_id": a.product.pk},
    "api/v1/products/<uuid:product_id>/image/": lambda a: {"product_id": a.product.pk},
    "api/v1/suppliers/<uuid:entry_id>/": lambda a: {"entry_id": a.supplier.pk},
    "api/v1/suppliers/<uuid:supplier_id>/contacts/": lambda a: {"supplier_id": a.supplier.pk},
    "api/v1/suppliers/<uuid:supplier_id>/contacts/<uuid:contact_id>/": lambda a: {
        "supplier_id": a.supplier.pk,
        "contact_id": a.contact.pk,
    },
    "api/v1/suppliers/<uuid:supplier_id>/products/": lambda a: {"supplier_id": a.supplier.pk},
    "api/v1/products/<uuid:product_id>/suppliers/": lambda a: {"product_id": a.product.pk},
    "api/v1/product-suppliers/<uuid:link_id>/": lambda a: {"link_id": a.link.pk},
    "api/v1/stores/<uuid:store_id>/products/lookup/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/inventory/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/inventory/movements/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/inventory/adjustments/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/inventory/adjustments/<uuid:adjustment_id>/": lambda a: {
        "store_id": a.store.pk,
        "adjustment_id": a.adjustment.pk,
    },
    "api/v1/stores/<uuid:store_id>/inventory/opening-balance/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/inventory/<uuid:product_id>/": lambda a: {
        "store_id": a.store.pk,
        "product_id": a.product.pk,
    },
    "api/v1/stores/<uuid:store_id>/sales/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/sales/<uuid:sale_id>/": lambda a: {
        "store_id": a.store.pk,
        "sale_id": a.sale.pk,
    },
    "api/v1/stores/<uuid:store_id>/sales/<uuid:sale_id>/receipt/": lambda a: {
        "store_id": a.store.pk,
        "sale_id": a.sale.pk,
    },
    "api/v1/customers/<uuid:entry_id>/": lambda a: {"entry_id": a.customer.pk},
    "api/v1/customers/<uuid:customer_id>/account/": lambda a: {"customer_id": a.customer.pk},
    "api/v1/customers/<uuid:customer_id>/account/opening-balance/": lambda a: {
        "customer_id": a.customer.pk
    },
    "api/v1/customers/<uuid:customer_id>/ledger/": lambda a: {"customer_id": a.customer.pk},
    "api/v1/customers/<uuid:customer_id>/ledger/<uuid:entry_id>/reverse/": lambda a: {
        "customer_id": a.customer.pk,
        "entry_id": a.ledger_entry.pk,
    },
    "api/v1/customers/<uuid:customer_id>/payments/": lambda a: {"customer_id": a.customer.pk},
    "api/v1/stores/<uuid:store_id>/sales/<uuid:sale_id>/void/": lambda a: {
        "store_id": a.store.pk,
        "sale_id": a.sale.pk,
    },
    "api/v1/stores/<uuid:store_id>/sales/<uuid:sale_id>/returns/": lambda a: {
        "store_id": a.store.pk,
        "sale_id": a.sale.pk,
    },
    "api/v1/stores/<uuid:store_id>/tills/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/tills/<uuid:till_id>/": lambda a: {
        "store_id": a.store.pk,
        "till_id": a.till.pk,
    },
    "api/v1/stores/<uuid:store_id>/cash-sessions/": lambda a: {"store_id": a.store.pk},
    "api/v1/stores/<uuid:store_id>/cash-sessions/current/": lambda a: {"store_id": a.store.pk},
    **{
        f"api/v1/stores/<uuid:store_id>/cash-sessions/<uuid:session_id>/{suffix}": (
            lambda a: {"store_id": a.store.pk, "session_id": a.cash_session.pk}
        )
        for suffix in ("", "movements/", "close/", "corrections/")
    },
}

# Catalog lookups of business A, compared before and after the attack.
CATALOG_MODELS = (Category, Brand, UnitOfMeasure, TaxRate)
MASTER_DATA_MODELS = (*CATALOG_MODELS, Product, PaymentMethod, Supplier, Customer)

# A body that passes validation for any endpoint, so lookups (not validators) decide.
BODY = {
    "name": "Taken over",
    "description": "",
    "reason": "Testing cross-tenant access",
    "version": 1,
    "permissions": [],
    "is_active": False,
}


@pytest.fixture
def world():
    a = create_business(email="owner@duka-a.example", name="Duka A")
    b = create_business(email="owner@duka-b.example", name="Duka B")
    store = add_store(a.organization, "BR2")
    cashier = add_staff(a.organization, email="cashier@duka-a.example", stores=[store])
    session = client_for(a.user, a.organization)  # creates an AuthSession for A's owner
    invitation = Invitation.objects.create(
        organization=a.organization,
        email="invitee@example.com",
        role=role(a.organization, Role.Template.CASHIER),
        all_stores=True,
        invited_by=a.user,
        token_hash="0" * 64,
        expires_at=timezone.now() + timedelta(days=7),
    )
    org = a.organization
    unit = UnitOfMeasure.objects.for_org(org).get(code="PCS")
    tax_rate = TaxRate.objects.for_org(org).get(name="VAT 16%")
    product = Product.objects.create(
        organization=org,
        sku="P000001",
        name="Milk 500ml",
        unit=unit,
        tax_rate=tax_rate,
        selling_price="60.00",
    )
    supplier = Supplier.objects.create(organization=org, code="S00001", name="Mumias Sugar")
    owner_ctx = context_for(a.membership)
    inventory_services.create_adjustment(
        owner_ctx,
        store,
        client_txn_id=uuid.uuid4(),
        reason_code="OPENING_BALANCE",
        lines=[
            inventory_services.AdjustmentLineInput(product=product, counted_quantity=Decimal(5))
        ],
    )
    till = Till.objects.create(organization=org, store=store, name="Till 1")
    cash_session = cash_services.open_session(
        owner_ctx, store, till=till, opening_float=Decimal(500), client_txn_id=uuid.uuid4()
    )
    customer = customer_services.create_customer(
        owner_ctx, name="Mama Mboga", credit_limit=Decimal(1000)
    )
    sale = sale_services.create_sale(
        owner_ctx,
        store,
        sale_services.SaleRequest(
            client_txn_id=uuid.uuid4(),
            items=[sale_services.ItemInput(product, Decimal(1), Decimal(60))],
            tenders=[],
            customer=customer,
            credit_amount=Decimal(60),
        ),
    ).sale
    adjustment = StockAdjustment.objects.create(
        organization=org,
        store=store,
        reason_code="FOUND",
        client_txn_id=uuid.uuid4(),
        created_by=a.user,
        occurred_at=timezone.now(),
    )
    return SimpleNamespace(
        a=SimpleNamespace(
            organization=a.organization,
            store=store,
            cashier=cashier,
            cashier_role=role(a.organization, Role.Template.CASHIER),
            session=AuthSession.objects.get(user=a.user),
            invitation=invitation,
            client=session,
            category=Category.objects.create(organization=org, name="Drinks"),
            brand=Brand.objects.create(organization=org, name="Kensalt"),
            unit=unit,
            tax_rate=tax_rate,
            product=product,
            supplier=supplier,
            contact=SupplierContact.objects.create(
                organization=org, supplier=supplier, name="Wanjiku", is_primary=True
            ),
            link=ProductSupplier.objects.create(
                organization=org, product=product, supplier=supplier, is_preferred=True
            ),
            identifier=ProductIdentifier.objects.create(
                organization=org, product=product, value="6161100000123", is_primary=True
            ),
            payment_method=PaymentMethod.objects.for_org(org).get(code="MPESA"),
            adjustment=adjustment,
            sale=sale,
            customer=customer,
            ledger_entry=CustomerLedgerEntry.objects.for_org(org).get(sale=sale),
            till=till,
            cash_session=cash_session,
        ),
        b_client=client_for(b.user, b.organization),
    )


def _snapshot(organization):
    return {
        "audit": AuditLog.objects.filter(organization=organization).count(),
        "stores": sorted(
            Store.objects.for_org(organization).values_list("pk", "name", "is_active")
        ),
        "roles": sorted(Role.objects.for_org(organization).values_list("pk", "name")),
        "members": sorted(
            Membership.objects.for_org(organization).values_list("pk", "status", "version")
        ),
        "sessions": sorted(
            AuthSession.objects.filter(organization=organization).values_list("pk", "revoked_at")
        ),
        "invitations": sorted(
            Invitation.objects.for_org(organization).values_list("pk", "revoked_at", "accepted_at")
        ),
        **{
            model.audit_name: sorted(
                model.objects.for_org(organization).values_list("pk", "is_active", "version")
            )
            for model in MASTER_DATA_MODELS
        },
        "contacts": sorted(
            SupplierContact.objects.for_org(organization).values_list("pk", "name", "is_primary")
        ),
        "links": sorted(
            ProductSupplier.objects.for_org(organization).values_list(
                "pk", "is_preferred", "supplier_sku", "min_order_qty"
            )
        ),
        "identifiers": sorted(
            ProductIdentifier.objects.for_org(organization).values_list("pk", "value", "is_primary")
        ),
        "stock": sorted(
            StockLevel.objects.for_org(organization).values_list(
                "pk", "quantity_on_hand", "version"
            )
        ),
        "movements": InventoryMovement.objects.for_org(organization).count(),
        "adjustments": StockAdjustment.objects.for_org(organization).count(),
        "sales": Sale.objects.for_org(organization).count(),
        "payments": Payment.objects.for_org(organization).count(),
        "accounts": sorted(
            CustomerAccount.objects.for_org(organization).values_list(
                "pk", "balance", "credit_limit", "status", "version"
            )
        ),
        "ledger": CustomerLedgerEntry.objects.for_org(organization).count(),
        "tills": sorted(Till.objects.for_org(organization).values_list("pk", "name", "version")),
        "cash_sessions": sorted(
            CashSession.objects.for_org(organization).values_list("pk", "status", "counted_cash")
        ),
        "cash_movements": CashMovement.objects.for_org(organization).count(),
        "sale_statuses": sorted(Sale.objects.for_org(organization).values_list("pk", "status")),
    }


def test_every_route_with_an_id_is_covered():
    missing = {r.path for r in api_routes() if r.has_path_params} - set(TARGETS)

    assert not missing, f"Register these routes in TARGETS: {sorted(missing)}"


def test_other_businesses_get_404_and_change_nothing(world):
    before = _snapshot(world.a.organization)
    failures = []

    for route in api_routes():
        if not route.has_path_params:
            continue
        url = route.url(**TARGETS[route.path](world.a))
        for method in route.methods:
            response = getattr(world.b_client, method.lower())(url, BODY, format="json")
            if response.status_code != 404:
                failures.append(f"{method} {url} -> {response.status_code}")

    assert not failures, "Cross-tenant access not refused:\n" + "\n".join(failures)
    assert _snapshot(world.a.organization) == before
    assert world.a.client.get("/api/v1/organization/").status_code == 200  # A's session intact


def test_list_endpoints_never_include_another_businesses_records(world):
    a_ids = {
        str(pk)
        for pk in [
            *Store.objects.for_org(world.a.organization).values_list("pk", flat=True),
            *Role.objects.for_org(world.a.organization).values_list("pk", flat=True),
            *Membership.objects.for_org(world.a.organization).values_list("pk", flat=True),
            world.a.invitation.pk,
            world.a.session.pk,
            *(
                pk
                for model in (
                    *MASTER_DATA_MODELS,
                    ProductIdentifier,
                    SupplierContact,
                    ProductSupplier,
                )
                for pk in model.objects.for_org(world.a.organization).values_list("pk", flat=True)
            ),
            world.a.organization.pk,
        ]
    }

    for route in api_routes():
        if route.has_path_params or "GET" not in route.methods or route.path.endswith("docs/"):
            continue
        body = world.b_client.get(route.url()).content.decode()
        leaked = [pk for pk in a_ids if pk in body]
        assert not leaked, f"/{route.path} leaked {leaked}"
