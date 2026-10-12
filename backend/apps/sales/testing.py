"""Test helpers for selling: a stocked shop and request builders.

Used by tests across apps; never imported by application code.
"""

import uuid
from collections.abc import Iterable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from django.db import transaction
from rest_framework.test import APIClient

from apps.cash import services as cash
from apps.cash.models import Till
from apps.catalog.models import Product, TaxRate, UnitOfMeasure
from apps.customers import services as customer_services
from apps.inventory import services as inventory
from apps.organizations.models import Role, Store
from apps.organizations.testing import (
    add_staff,
    add_store,
    client_for,
    context_for,
    create_business,
)
from apps.payments.models import PaymentMethod


def build_shop() -> SimpleNamespace:
    """A shop with stock: milk (80, 16% VAT), bread (60, zero-rated), rice by the kg,
    a delivery service, a manager and two cashiers."""
    registered = create_business()
    org = registered.organization
    pcs = UnitOfMeasure.objects.for_org(org).get(code="PCS")
    kg = UnitOfMeasure.objects.for_org(org).get(code="KG")
    vat = TaxRate.objects.for_org(org).get(name="VAT 16%")
    zero = TaxRate.objects.for_org(org).get(name="Zero-rated")

    def product(
        name: str,
        sku: str,
        price: str,
        unit: UnitOfMeasure = pcs,
        tax: TaxRate = vat,
        **fields: Any,
    ) -> Product:
        return Product.objects.create(
            organization=org,
            sku=sku,
            name=name,
            unit=unit,
            tax_rate=tax,
            selling_price=Decimal(price),
            **fields,
        )

    shop = SimpleNamespace(
        organization=org,
        store=registered.store,
        branch=add_store(org, "BR2", "Branch 2"),
        owner_user=registered.user,
        owner=client_for(registered.user, org),
        owner_ctx=context_for(registered.membership),
        milk=product("Milk 500ml", "MILK", "80", default_cost=Decimal(60)),
        bread=product("Bread 400g", "BREAD", "60", tax=zero),
        rice=product("Rice (loose)", "RICE", "190", unit=kg),
        delivery=product(
            "Delivery", "DELIVERY", "150", track_inventory=False, etims_product_type="3"
        ),
        cash=PaymentMethod.objects.for_org(org).get(code="CASH"),
        mpesa=PaymentMethod.objects.for_org(org).get(code="MPESA"),
        card=PaymentMethod.objects.for_org(org).get(code="CARD"),
    )
    manager = add_staff(
        org, email="m@duka-a.example", template=Role.Template.MANAGER, all_stores=True
    )
    cashier = add_staff(org, email="c@duka-a.example", stores=[registered.store])
    cashier2 = add_staff(org, email="c2@duka-a.example", stores=[registered.store])
    shop.manager = client_for(manager.user, org)
    shop.cashier_user = cashier.user
    shop.cashier = client_for(cashier.user, org)
    shop.cashier2 = client_for(cashier2.user, org)
    shop.cashier_ctx = context_for(cashier)
    shop.cashier2_ctx = context_for(cashier2)
    with transaction.atomic():
        inventory.create_adjustment(
            shop.owner_ctx,
            shop.store,
            client_txn_id=uuid.uuid4(),
            reason_code="OPENING_BALANCE",
            lines=[
                inventory.AdjustmentLineInput(product=shop.milk, counted_quantity=Decimal(10)),
                inventory.AdjustmentLineInput(product=shop.bread, counted_quantity=Decimal(5)),
                inventory.AdjustmentLineInput(product=shop.rice, counted_quantity=Decimal(20)),
            ],
        )
    # Cash needs an open till (store.require_cash_session): everyone who sells gets one.
    shop.sessions = {}
    for name, ctx in (
        ("owner", shop.owner_ctx),
        ("manager", context_for(manager)),
        ("cashier", shop.cashier_ctx),
        ("cashier2", shop.cashier2_ctx),
    ):
        till = Till.objects.create(organization=org, store=shop.store, name=f"Till {name}")
        shop.sessions[name] = cash.open_session(
            ctx, shop.store, till=till, opening_float=Decimal(1000), client_txn_id=uuid.uuid4()
        )
    shop.customer = customer_services.create_customer(
        shop.owner_ctx, name="Mama Mboga", phone="+254712345678", credit_limit=Decimal(500)
    )
    return shop


def item(product: Product, quantity: Any = "1", price: Any = None, **extra: Any) -> dict[str, Any]:
    return {
        "product_id": str(product.pk),
        "quantity": str(quantity),
        "unit_price": str(price if price is not None else product.selling_price),
        **extra,
    }


def tender(method: PaymentMethod, amount: Any, **extra: Any) -> dict[str, Any]:
    return {"payment_method_id": str(method.pk), "amount": str(amount), **extra}


def sell(
    client: APIClient,
    shop: SimpleNamespace,
    items: list[dict[str, Any]],
    tenders: Iterable[dict[str, Any]] = (),
    store: Store | None = None,
    key: str | None = None,
    **extra: Any,
) -> Any:
    body = {
        "client_txn_id": extra.pop("client_txn_id", str(uuid.uuid4())),
        "items": items,
        "tenders": list(tenders),
        **extra,
    }
    return client.post(
        f"/api/v1/stores/{(store or shop.store).pk}/sales/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )
