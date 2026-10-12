import threading
import uuid
from decimal import Decimal

import pytest
from django.db import connection

from apps.audit.models import AuditLog
from apps.customers.models import CustomerAccount, CustomerLedgerEntry
from apps.inventory.models import InventoryMovement, StockLevel
from apps.organizations.models import DocumentSequence
from apps.organizations.testing import create_business
from apps.payments.models import Payment
from apps.sales import services
from apps.sales.models import Sale
from apps.sales.testing import build_shop, item, sell, tender

pytestmark = pytest.mark.django_db


def _stock(shop, product, store=None):
    level = StockLevel.objects.for_org(shop.organization).filter(
        store=store or shop.store, product=product
    )
    return level.values_list("quantity_on_hand", flat=True).first()


# --- Completing a sale ----------------------------------------------------------------------


def test_a_cash_sale_prices_on_the_server_gives_change_and_moves_stock(shop):
    response = sell(
        shop.cashier,
        shop,
        [item(shop.milk, 2, scanned_code="6161100000123"), item(shop.bread)],
        [tender(shop.cash, "220.00", tendered="500")],
    )
    assert response.status_code == 201, response.json()
    sale = response.json()
    # The example in docs/API.md: 16% VAT inside 160.00 is 22.07; bread is zero-rated.
    assert (sale["subtotal"], sale["tax_total"], sale["total"]) == (
        "220.0000",
        "22.0700",
        "220.0000",
    )
    assert (sale["amount_paid"], sale["change_given"]) == ("220.0000", "280.0000")
    assert sale["receipt_number"].startswith("MAIN-")
    assert sale["receipt_number"].endswith("000001")
    assert sale["cashier"]["name"] == shop.cashier_user.full_name
    assert [i["product_name"] for i in sale["items"]] == ["Milk 500ml", "Bread 400g"]
    assert sale["payments"] == [
        {
            "method": "CASH",
            "method_name": "Cash",
            "kind": "CASH",
            "direction": "IN",
            "amount": "220.0000",
            "tendered": "500.0000",
            "reference": "",
            "status": "CONFIRMED",
        }
    ]
    assert (_stock(shop, shop.milk), _stock(shop, shop.bread)) == (8, 4)
    movements = InventoryMovement.objects.for_org(shop.organization).filter(movement_type="SALE")
    assert (
        sorted(m.sale_item.sale_id for m in movements if m.sale_item) == [uuid.UUID(sale["id"])] * 2
    )
    assert AuditLog.objects.filter(action="sale.completed").count() == 1

    second = sell(shop.cashier, shop, [item(shop.delivery)], [tender(shop.card, "150")])
    assert second.json()["receipt_number"].endswith("000002")


def test_mixed_cash_and_mpesa_needs_the_mpesa_code_and_it_works_once(shop):
    items = [item(shop.milk, 3)]  # 240.00
    no_code = sell(shop.cashier, shop, items, [tender(shop.cash, 40), tender(shop.mpesa, 200)])
    assert no_code.status_code == 400
    assert no_code.json()["errors"][0]["pointer"] == "/tenders/1/reference"

    paid = sell(
        shop.cashier,
        shop,
        items,
        [tender(shop.cash, 40, tendered=50), tender(shop.mpesa, 200, reference=" sk7abc12de ")],
    )
    assert paid.status_code == 201, paid.json()
    assert [p["reference"] for p in paid.json()["payments"]] == ["", "SK7ABC12DE"]
    assert paid.json()["change_given"] == "10.0000"

    reused = sell(
        shop.cashier, shop, [item(shop.bread)], [tender(shop.mpesa, 60, reference="SK7ABC12DE")]
    )
    assert reused.status_code == 422
    assert reused.json()["code"] == "PAYMENT_REFERENCE_USED"


def test_payments_must_cover_the_total_exactly(shop):
    short = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.card, "70")])
    assert short.status_code == 422
    body = short.json()
    assert body["code"] == "TENDERS_DO_NOT_MATCH_TOTAL"
    assert body["errors"][0]["meta"] == {"total": "80.00", "paid": "70.00"}
    assert "10.00 still to pay" in body["detail"]

    change_on_card = sell(
        shop.cashier, shop, [item(shop.milk)], [tender(shop.card, "80", tendered="100")]
    )
    assert change_on_card.status_code == 400
    two_cash = sell(
        shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, "40"), tender(shop.cash, "40")]
    )
    assert two_cash.json()["errors"][0]["code"] == "DUPLICATE_CASH"
    assert Sale.objects.for_org(shop.organization).count() == 0


def test_a_stale_price_is_refused_with_the_current_one(shop):
    response = sell(shop.cashier, shop, [item(shop.milk, price="75")], [tender(shop.cash, 75)])
    assert response.status_code == 409
    error = response.json()["errors"][0]
    assert error["pointer"] == "/items/0/unit_price"
    assert (error["meta"]["shown"], error["meta"]["current"]) == ("75.0000", "80.0000")


def test_overriding_a_price_needs_permission_and_a_reason(shop):
    line = item(shop.milk, price="75", price_override=True)
    assert sell(shop.cashier, shop, [line], [tender(shop.cash, 75)]).status_code == 403
    no_reason = sell(shop.owner, shop, [line], [tender(shop.cash, 75)])
    assert no_reason.json()["errors"][0]["pointer"] == "/items/0/override_reason"

    line["override_reason"] = "Dented pack"
    sold = sell(shop.owner, shop, [line], [tender(shop.cash, 75)])
    assert sold.status_code == 201, sold.json()
    line_out = sold.json()["items"][0]
    assert (line_out["unit_price"], line_out["list_price"], line_out["price_overridden"]) == (
        "75.0000",
        "80.0000",
        True,
    )


def test_discounts_need_permission(shop):
    discounted = [item(shop.milk, discount_amount="10")]
    assert sell(shop.cashier, shop, discounted, [tender(shop.cash, 70)]).status_code == 403
    sold = sell(shop.manager, shop, discounted, [tender(shop.cash, 70)], order_discount="0")
    assert sold.status_code == 201, sold.json()
    assert (sold.json()["discount_total"], sold.json()["total"]) == ("10.0000", "70.0000")


def test_not_enough_stock_leaves_nothing_behind(shop):
    response = sell(shop.cashier, shop, [item(shop.bread, 6)], [tender(shop.cash, 360)])
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INSUFFICIENT_STOCK"
    assert body["errors"][0]["pointer"] == "/items/0/quantity"
    assert body["errors"][0]["meta"]["available"] == "5"
    assert Sale.objects.for_org(shop.organization).count() == 0
    assert Payment.objects.for_org(shop.organization).count() == 0
    assert _stock(shop, shop.bread) == 5
    # The receipt number wasn't used up either.
    assert (
        sell(shop.cashier, shop, [item(shop.bread)], [tender(shop.cash, 60)])
        .json()["receipt_number"]
        .endswith("000001")
    )


def test_whole_units_unless_sold_by_weight(shop):
    half_milk = sell(shop.cashier, shop, [item(shop.milk, "0.5")], [tender(shop.cash, 40)])
    assert half_milk.json()["errors"][0]["code"] == "FRACTION_NOT_ALLOWED"
    rice = sell(shop.cashier, shop, [item(shop.rice, "1.25")], [tender(shop.cash, "237.50")])
    assert rice.status_code == 201, rice.json()
    assert _stock(shop, shop.rice) == Decimal("18.75")


def test_inactive_products_cant_be_sold(shop):
    shop.milk.is_active = False
    shop.milk.save()
    response = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)])
    assert response.json()["code"] == "PRODUCT_INACTIVE"


def test_retries_never_sell_twice(shop):
    txn = str(uuid.uuid4())
    key = str(uuid.uuid4())
    first = sell(
        shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)], key=key, client_txn_id=txn
    )
    replay = sell(
        shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)], key=key, client_txn_id=txn
    )
    assert replay.headers["Idempotent-Replayed"] == "true"
    # The same sale under a new key (a till re-sending after a lost response).
    resent = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)], client_txn_id=txn)
    assert resent.status_code == 200
    assert first.json()["id"] == replay.json()["id"] == resent.json()["id"]
    assert _stock(shop, shop.milk) == 9


def test_cashiers_see_their_own_sales_managers_see_all(shop):
    mine = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)]).json()
    theirs = sell(shop.cashier2, shop, [item(shop.bread)], [tender(shop.cash, 60)]).json()
    url = f"/api/v1/stores/{shop.store.pk}/sales/"
    assert [s["id"] for s in shop.cashier.get(url).json()["results"]] == [mine["id"]]
    assert {s["id"] for s in shop.manager.get(url).json()["results"]} == {mine["id"], theirs["id"]}
    assert shop.cashier.get(f"{url}{theirs['id']}/").status_code == 404
    listed = shop.manager.get(f"{url}?search={mine['receipt_number']}").json()["results"]
    assert (listed[0]["item_count"], listed[0]["methods"]) == (1, ["Cash"])


def test_other_businesses_ids_are_rejected(shop):
    other = create_business(email="owner@duka-b.example", name="Duka B")
    from apps.payments.models import PaymentMethod

    their_cash = PaymentMethod.objects.for_org(other.organization).get(code="CASH")
    response = sell(shop.cashier, shop, [item(shop.milk)], [tender(their_cash, 80)])
    assert response.status_code == 400
    assert Sale.objects.for_org(shop.organization).count() == 0


def test_a_failure_part_way_rolls_everything_back(shop, monkeypatch):
    def broken_audit(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(services, "record_audit", broken_audit)
    with pytest.raises(RuntimeError):
        sell(
            shop.cashier,
            shop,
            [item(shop.milk, 2)],
            [tender(shop.mpesa, 160, reference="QWE123RTY0")],
        )
    assert Sale.objects.for_org(shop.organization).count() == 0
    assert Payment.objects.for_org(shop.organization).count() == 0
    assert (
        InventoryMovement.objects.for_org(shop.organization).filter(movement_type="SALE").count()
        == 0
    )
    assert _stock(shop, shop.milk) == 10
    assert not DocumentSequence.objects.for_org(shop.organization).filter(last_value__gt=0).exists()


# --- Receipts ----------------------------------------------------------------------------------


def test_the_receipt_has_the_tax_breakdown_and_reprints_are_audited(shop):
    sale = sell(
        shop.cashier, shop, [item(shop.milk, 2), item(shop.bread)], [tender(shop.cash, 220)]
    ).json()
    url = f"/api/v1/stores/{shop.store.pk}/sales/{sale['id']}/receipt/"
    receipt = shop.cashier.get(url).json()
    assert receipt["business"]["name"] == "Duka A"
    assert receipt["taxes"] == [
        {"name": "VAT 16%", "rate": "0.1600", "taxable_amount": "137.93", "tax_amount": "22.07"},
        {"name": "Zero-rated", "rate": "0.0000", "taxable_amount": "60.00", "tax_amount": "0.00"},
    ]
    assert receipt["reprint"] is False
    assert shop.cashier.get(f"{url}?reprint=true").json()["reprint"] is True
    assert AuditLog.objects.filter(action="sale.receipt_reprinted").count() == 1


# --- Credit --------------------------------------------------------------------------------------


def _owed(shop):
    return CustomerAccount.objects.for_org(shop.organization).get(customer=shop.customer).balance


def test_part_of_a_sale_on_credit_goes_on_the_account(shop):
    response = sell(
        shop.cashier,
        shop,
        [item(shop.milk, 5)],  # 400.00
        [tender(shop.cash, 100)],
        customer_id=str(shop.customer.pk),
        credit_amount="300",
    )
    assert response.status_code == 201, response.json()
    sale = response.json()
    assert (sale["amount_paid"], sale["amount_on_credit"]) == ("100.0000", "300.0000")
    assert sale["customer"]["name"] == "Mama Mboga"
    assert _owed(shop) == 300
    entry = CustomerLedgerEntry.objects.for_org(shop.organization).get()
    assert (entry.entry_type, entry.amount, entry.balance_after, entry.sale_id) == (
        "CREDIT_SALE",
        300,
        300,
        uuid.UUID(sale["id"]),
    )
    receipt = shop.cashier.get(f"/api/v1/stores/{shop.store.pk}/sales/{sale['id']}/receipt/").json()
    assert receipt["account"] == {"charged": "300.00", "balance_after": "300.00"}


def test_credit_is_limited_unless_allowed_to_exceed(shop):
    over = sell(
        shop.cashier,
        shop,
        [item(shop.milk, 7)],  # 560.00 > 500 limit
        customer_id=str(shop.customer.pk),
        credit_amount="560",
    )
    assert over.status_code == 422
    body = over.json()
    assert body["code"] == "CREDIT_LIMIT_EXCEEDED"
    assert body["errors"][0]["meta"] == {
        "credit_limit": "500.00",
        "balance": "0.00",
        "available": "500.00",
    }
    assert _stock(shop, shop.milk) == 10
    allowed = sell(
        shop.owner,
        shop,
        [item(shop.milk, 7)],
        customer_id=str(shop.customer.pk),
        credit_amount="560",
    )
    assert allowed.status_code == 201
    assert _owed(shop) == 560


def test_credit_needs_a_customer_and_an_active_account(shop):
    no_customer = sell(shop.cashier, shop, [item(shop.milk)], credit_amount="80")
    assert no_customer.json()["errors"][0]["pointer"] == "/customer_id"
    CustomerAccount.objects.for_org(shop.organization).update(status="FROZEN")
    frozen = sell(
        shop.cashier, shop, [item(shop.milk)], customer_id=str(shop.customer.pk), credit_amount="80"
    )
    assert frozen.json()["code"] == "CUSTOMER_FROZEN"


# --- Concurrency ----------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_cashiers_race_for_the_last_unit_and_exactly_one_wins():
    shop = build_shop()
    StockLevel.objects.for_org(shop.organization).filter(product=shop.bread).update(
        quantity_on_hand=1
    )
    barrier = threading.Barrier(2)
    outcomes = []

    def buy(ctx):
        try:
            barrier.wait()
            services.create_sale(
                ctx,
                shop.store,
                services.SaleRequest(
                    client_txn_id=uuid.uuid4(),
                    items=[services.ItemInput(shop.bread, Decimal(1), Decimal(60))],
                    tenders=[services.TenderInput(shop.cash, Decimal(60))],
                ),
            )
            outcomes.append("sold")
        except Exception as exc:
            outcomes.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=buy, args=(ctx,)) for ctx in (shop.cashier_ctx, shop.cashier2_ctx)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["InsufficientStock", "sold"]
    assert _stock(shop, shop.bread) == 0
    assert Sale.objects.for_org(shop.organization).count() == 1
