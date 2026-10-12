import uuid
from decimal import Decimal

import pytest
from django.db import transaction

from apps.audit.models import AppendOnlyError, AuditLog
from apps.cash.models import CashMovement, CashSession, Till
from apps.sales.testing import item, sell, tender

pytestmark = pytest.mark.django_db


def _url(shop, path=""):
    return f"/api/v1/stores/{shop.store.pk}/{path}"


def _post(client, url, body):
    return client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))


def _session_url(shop, who="cashier", path=""):
    return _url(shop, f"cash-sessions/{shop.sessions[who].pk}/{path}")


def _move(shop, client, kind, amount, reason="Bought change", who="cashier"):
    return _post(
        client,
        _session_url(shop, who, "movements/"),
        {
            "client_txn_id": str(uuid.uuid4()),
            "movement_type": kind,
            "amount": str(amount),
            "reason": reason,
        },
    )


def _close(shop, client, counted, who="cashier", **extra):
    return _post(client, _session_url(shop, who, "close/"), {"counted_cash": str(counted), **extra})


# --- Opening --------------------------------------------------------------------------------------


def test_every_store_starts_with_a_till(shop):
    assert Till.objects.for_org(shop.organization).filter(store=shop.store, name="Till 1").exists()


def test_one_session_per_till_and_per_person(shop):
    till = Till.objects.for_org(shop.organization).get(store=shop.store, name="Till 1")
    open_again = _post(
        shop.cashier,
        _url(shop, "cash-sessions/"),
        {"client_txn_id": str(uuid.uuid4()), "till_id": str(till.pk), "opening_float": "500"},
    )
    assert open_again.json()["code"] == "SESSION_ALREADY_OPEN"  # the cashier has one already

    taken = shop.sessions["manager"].till
    _close(shop, shop.manager, "1000", who="manager")
    other = _post(
        shop.cashier2,
        _url(shop, "cash-sessions/"),
        {"client_txn_id": str(uuid.uuid4()), "till_id": str(taken.pk), "opening_float": "0"},
    )
    assert other.json()["code"] == "SESSION_ALREADY_OPEN"


def test_the_current_session_is_blind(shop):
    current = shop.cashier.get(_url(shop, "cash-sessions/current/")).json()["session"]
    assert current["id"] == str(shop.sessions["cashier"].pk)
    assert "expected_cash" not in current
    assert shop.cashier.get(_url(shop, "cash-sessions/")).status_code == 403  # managers only


# --- Cash in the drawer ---------------------------------------------------------------------------


def test_cash_sales_need_an_open_till(shop):
    _close(shop, shop.cashier, "1000")
    refused = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)])
    assert refused.status_code == 422
    assert refused.json()["code"] == "CASH_SESSION_REQUIRED"
    by_card = sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.card, 80)])
    assert by_card.status_code == 201  # no cash, no till needed

    shop.store.require_cash_session = False
    shop.store.save()
    assert sell(shop.cashier, shop, [item(shop.milk)], [tender(shop.cash, 80)]).status_code == 201


def test_close_out_compares_the_blind_count_with_what_should_be_there(shop):
    # 1000 float + 220 cash sale (500 given, 280 change) + 100 pay-in - 50 pay-out - 300 drop
    sell(
        shop.cashier,
        shop,
        [item(shop.milk, 2), item(shop.bread)],
        [tender(shop.cash, 220, tendered=500)],
    )
    sell(shop.cashier, shop, [item(shop.bread)], [tender(shop.mpesa, 60, reference="QWE123RTY0")])
    assert _move(shop, shop.cashier, "PAY_IN", 100).status_code == 201
    assert (
        _move(shop, shop.cashier, "PAY_OUT", 50, reason="Airtime for the shop").status_code == 201
    )
    assert _move(shop, shop.cashier, "DROP", 300, reason="To the safe").status_code == 201
    too_much = _move(shop, shop.cashier, "PAY_OUT", 5000)
    assert too_much.json()["code"] == "NOT_ENOUGH_CASH"

    short = _close(shop, shop.cashier, "860")  # expected 970: 110 out, over the 100 threshold
    assert short.status_code == 400
    assert short.json()["errors"][0]["pointer"] == "/variance_reason"

    closed = _close(
        shop,
        shop.cashier,
        "860",
        variance_reason="A 100 note and change missing",
        denomination_count={"500": 1, "100": 3, "50": 1, "10": 1},
    )
    assert closed.status_code == 200, closed.json()
    body = closed.json()
    report = body["report"]
    assert (report["expected_cash"], report["counted_cash"], report["variance"]) == (
        "970.0000",
        "860.0000",
        "-110.0000",
    )
    assert report["sales_count"] == 2
    assert [(m["method"], m["total"]) for m in report["by_method"]] == [
        ("Cash", "220.0000"),
        ("M-Pesa", "60.0000"),
    ]
    assert [m["movement_type"] for m in body["movements"]] == ["PAY_IN", "PAY_OUT", "DROP"]
    assert AuditLog.objects.filter(action="cash_session.variance_alert").count() == 1


def test_counts_by_note_must_add_up(shop):
    response = _close(shop, shop.cashier, "1000", denomination_count={"500": 1, "100": 4})
    assert response.json()["errors"][0]["code"] == "DOES_NOT_ADD_UP"


def test_a_small_variance_needs_no_reason(shop):
    closed = _close(shop, shop.cashier, "990")  # 10 short, under the 100 threshold
    assert closed.status_code == 200
    assert closed.json()["report"]["variance"] == "-10.0000"


def test_a_closed_session_never_changes_but_can_be_corrected(shop):
    _close(shop, shop.cashier, "900", variance_reason="Unknown")
    session = CashSession.objects.for_org(shop.organization).get(pk=shop.sessions["cashier"].pk)
    assert (
        _move(shop, shop.cashier, "PAY_IN", 10).json()["detail"] == "This till session is closed."
    )
    with pytest.raises(Exception, match="closed"), transaction.atomic():
        CashSession.unscoped.filter(pk=session.pk).update(counted_cash=Decimal(1000))

    correction = {
        "client_txn_id": str(uuid.uuid4()),
        "amount": "100",
        "reason": "Found under the tray",
    }
    assert (
        _post(shop.manager, _session_url(shop, path="corrections/"), correction).status_code == 403
    )
    fixed = _post(shop.owner, _session_url(shop, path="corrections/"), correction)
    assert fixed.status_code == 201, fixed.json()
    assert fixed.json()["report"]["variance_after_corrections"] == "0.0000"

    movement = CashMovement.objects.for_org(shop.organization).get(movement_type="CORRECTION")
    with pytest.raises(AppendOnlyError):
        movement.save()


def test_only_the_opener_or_a_manager_closes_a_till(shop):
    assert _close(shop, shop.cashier2, "1000").status_code == 403
    assert _close(shop, shop.manager, "1000").status_code == 200


def test_customer_cash_payments_go_through_the_till(shop):
    sell(
        shop.owner,
        shop,
        [item(shop.milk, 5)],
        customer_id=str(shop.customer.pk),
        credit_amount="400",
    )
    paid = _post(
        shop.cashier,
        f"/api/v1/customers/{shop.customer.pk}/payments/",
        {
            "client_txn_id": str(uuid.uuid4()),
            "store_id": str(shop.store.pk),
            "payment_method_id": str(shop.cash.pk),
            "amount": "100",
        },
    )
    assert paid.status_code == 201
    closed = _close(shop, shop.cashier, "1100")
    assert closed.json()["report"]["cash_in"] == "100.0000"
