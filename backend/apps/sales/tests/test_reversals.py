import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.customers.models import CustomerAccount
from apps.inventory.models import InventoryMovement, StockLevel
from apps.payments.models import Payment
from apps.sales.models import Sale
from apps.sales.testing import item, sell, tender

pytestmark = pytest.mark.django_db


def _stock(shop, product):
    return (
        StockLevel.objects.for_org(shop.organization)
        .get(store=shop.store, product=product)
        .quantity_on_hand
    )


def _owed(shop):
    return CustomerAccount.objects.for_org(shop.organization).get(customer=shop.customer).balance


def _post(client, url, body):
    return client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))


def _void(shop, client, sale, reason="Rang up twice"):
    return _post(
        client, f"/api/v1/stores/{shop.store.pk}/sales/{sale['id']}/void/", {"reason": reason}
    )


def _return(shop, client, sale, items, refund_to="PAYMENT", method=None, **extra):
    body = {
        "client_txn_id": str(uuid.uuid4()),
        "reason": "Customer changed their mind",
        "items": items,
        "refund_to": refund_to,
        **extra,
    }
    if method is not None:
        body["payment_method_id"] = str(method.pk)
    return _post(client, f"/api/v1/stores/{shop.store.pk}/sales/{sale['id']}/returns/", body)


def _expected_cash(shop, who="cashier"):
    from apps.cash.services import expected_cash

    return expected_cash(shop.sessions[who])


# --- Voids ----------------------------------------------------------------------------------------


def test_a_void_puts_everything_back(shop):
    sale = sell(
        shop.cashier,
        shop,
        [item(shop.milk, 2), item(shop.bread)],
        [tender(shop.cash, 220, tendered=500)],
    ).json()
    assert _expected_cash(shop) == 1220

    assert _void(shop, shop.cashier, sale).status_code == 403  # cashiers can't void
    voided = _void(shop, shop.manager, sale)
    assert voided.status_code == 200, voided.json()
    body = voided.json()
    assert body["status"] == "VOIDED"
    assert body["void_reason"] == "Rang up twice"
    assert (_stock(shop, shop.milk), _stock(shop, shop.bread)) == (10, 5)
    back = InventoryMovement.objects.for_org(shop.organization).filter(movement_type="SALE_RETURN")
    assert back.count() == 2
    refund = Payment.objects.for_org(shop.organization).get(direction="OUT")
    assert (refund.purpose, refund.amount, refund.cash_session_id) == (
        "SALE_REFUND",
        220,
        shop.sessions["cashier"].pk,
    )
    assert _expected_cash(shop) == 1000
    assert _void(shop, shop.manager, sale).json()["detail"] == "This sale is already voided."


def test_a_void_takes_the_credit_off_the_account(shop):
    sale = sell(
        shop.owner,
        shop,
        [item(shop.milk, 5)],
        customer_id=str(shop.customer.pk),
        credit_amount="400",
    ).json()
    assert _owed(shop) == 400
    assert _void(shop, shop.owner, sale).status_code == 200
    assert _owed(shop) == 0


def test_only_today_and_while_the_till_is_open(shop):
    sale = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)]).json()
    Sale.objects.for_org(shop.organization).filter(pk=sale["id"]).update(
        occurred_at=timezone.now() - timedelta(days=1)
    )
    late = _void(shop, shop.manager, sale)
    assert late.json()["code"] == "VOID_TOO_LATE"

    today = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)]).json()
    _post(
        shop.cashier,
        f"/api/v1/stores/{shop.store.pk}/cash-sessions/{shop.sessions['cashier'].pk}/close/",
        {"counted_cash": "1160"},
    )
    closed = _void(shop, shop.manager, today)
    assert closed.json()["code"] == "VOID_TOO_LATE"
    assert "closed" in closed.json()["detail"]


# --- Returns --------------------------------------------------------------------------------------


def test_a_partial_return_refunds_cash_and_restocks(shop):
    sale = sell(
        shop.cashier, shop, [item(shop.milk, 3), item(shop.bread, 2)], [tender(shop.cash, 360)]
    ).json()
    response = _return(
        shop,
        shop.manager,
        sale,
        [{"line_no": 1, "quantity": "1"}, {"line_no": 2, "quantity": "1", "restock": False}],
        method=shop.cash,
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    [returned] = body["returns"]
    assert returned["return_number"].startswith("MAIN-R")
    assert (returned["total"], returned["refund_method"]) == ("140.0000", "Cash")
    assert [i["returned_quantity"] for i in body["items"]] == ["1.000", "1.000"]
    assert _stock(shop, shop.milk) == 8  # back on the shelf
    assert _stock(shop, shop.bread) == 3  # damaged: not restocked
    # The refund came out of the manager's own till.
    refund = Payment.objects.for_org(shop.organization).get(direction="OUT")
    assert (refund.amount, refund.cash_session_id) == (140, shop.sessions["manager"].pk)
    # Nothing left to void once items came back.
    assert _void(shop, shop.manager, sale).status_code == 422


def test_never_more_than_was_sold_and_the_last_unit_gets_the_exact_remainder(shop):
    # 3 at 80 with a 10 discount on the line: 230 for 3 doesn't split evenly.
    sale = sell(
        shop.manager, shop, [item(shop.milk, 3, discount_amount="10")], [tender(shop.cash, 230)]
    ).json()
    first = _return(shop, shop.manager, sale, [{"line_no": 1, "quantity": "2"}], method=shop.cash)
    assert first.json()["returns"][0]["total"] == "153.3300"
    too_many = _return(
        shop, shop.manager, sale, [{"line_no": 1, "quantity": "2"}], method=shop.cash
    )
    assert too_many.json()["code"] == "RETURN_EXCEEDS_SOLD"
    last = _return(shop, shop.manager, sale, [{"line_no": 1, "quantity": "1"}], method=shop.cash)
    assert last.json()["returns"][1]["total"] == "76.6700"  # 153.33 + 76.67 = 230.00


def test_a_return_can_come_off_the_customers_account(shop):
    sale = sell(
        shop.owner,
        shop,
        [item(shop.milk, 5)],
        customer_id=str(shop.customer.pk),
        credit_amount="400",
    ).json()
    response = _return(
        shop, shop.manager, sale, [{"line_no": 1, "quantity": "2"}], refund_to="ACCOUNT"
    )
    assert response.status_code == 201, response.json()
    assert _owed(shop) == 240
    assert Payment.objects.for_org(shop.organization).filter(direction="OUT").count() == 0


def test_a_paid_up_customer_gets_money_not_negative_credit(shop):
    sale = sell(
        shop.owner,
        shop,
        [item(shop.milk)],
        [tender(shop.card, 80)],
        customer_id=str(shop.customer.pk),
    ).json()
    response = _return(
        shop, shop.manager, sale, [{"line_no": 1, "quantity": "1"}], refund_to="ACCOUNT"
    )
    assert response.json()["code"] == "REFUND_EXCEEDS_BALANCE"
    by_mpesa = _return(
        shop, shop.manager, sale, [{"line_no": 1, "quantity": "1"}], method=shop.mpesa
    )
    assert by_mpesa.status_code == 201


def test_returns_need_permission_and_are_recorded_once(shop):
    sale = sell(shop.cashier, shop, [item(shop.milk, 2)], [tender(shop.card, 160)]).json()
    assert (
        _return(
            shop, shop.cashier, sale, [{"line_no": 1, "quantity": "1"}], method=shop.card
        ).status_code
        == 403
    )
    txn = str(uuid.uuid4())
    first = _return(
        shop,
        shop.manager,
        sale,
        [{"line_no": 1, "quantity": "1"}],
        method=shop.card,
        client_txn_id=txn,
    )
    again = _return(
        shop,
        shop.manager,
        sale,
        [{"line_no": 1, "quantity": "1"}],
        method=shop.card,
        client_txn_id=txn,
    )
    assert (first.status_code, again.status_code) == (201, 200)
    assert len(again.json()["returns"]) == 1
    assert _stock(shop, shop.milk) == Decimal(9)
