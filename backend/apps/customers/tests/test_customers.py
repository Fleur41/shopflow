import uuid
from decimal import Decimal

import pytest
from django.db import transaction

from apps.audit.models import AppendOnlyError, AuditLog
from apps.customers.models import CustomerAccount, CustomerLedgerEntry
from apps.payments.models import Payment
from apps.sales.testing import item, sell

pytestmark = pytest.mark.django_db


def _customers(client, query=""):
    return client.get(f"/api/v1/customers/{query}")


def _pay(shop, client, amount, method=None, key=None, txn=None, **extra):
    return client.post(
        f"/api/v1/customers/{shop.customer.pk}/payments/",
        {
            "client_txn_id": txn or str(uuid.uuid4()),
            "store_id": str(shop.store.pk),
            "payment_method_id": str((method or shop.cash).pk),
            "amount": str(amount),
            **extra,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


def _on_credit(shop, amount):
    """Sell milk (80 each) on credit."""
    response = sell(
        shop.owner,
        shop,
        [item(shop.milk, int(amount) // 80)],
        customer_id=str(shop.customer.pk),
        credit_amount=str(amount),
    )
    assert response.status_code == 201, response.json()


def _balance(shop):
    return CustomerAccount.objects.for_org(shop.organization).get(customer=shop.customer).balance


# --- Customers ------------------------------------------------------------------------------------


def test_cashiers_add_customers_but_only_some_roles_set_credit(shop):
    plain = shop.cashier.post("/api/v1/customers/", {"name": "Otieno"}, format="json")
    assert plain.status_code == 201, plain.json()
    assert plain.json()["account"]["credit_limit"] is None
    with_credit = shop.manager.post(
        "/api/v1/customers/", {"name": "Akinyi", "credit_limit": "1000"}, format="json"
    )
    assert with_credit.status_code == 403  # customers.set_credit_limit is the owner's
    owner = shop.owner.post(
        "/api/v1/customers/", {"name": "Akinyi", "credit_limit": "1000"}, format="json"
    )
    assert owner.json()["account"]["available_credit"] == "1000.0000"


def test_contact_details_are_masked_without_permission(shop):
    for_manager = _customers(shop.manager).json()["results"][0]
    for_cashier = _customers(shop.cashier).json()["results"][0]
    assert for_manager["phone"] == "+254712345678"
    assert for_cashier["phone"] == "+254•••678"


def test_search_by_name_or_phone_digits_and_balance(shop):
    shop.owner.post("/api/v1/customers/", {"name": "Baraka Otieno"}, format="json")
    assert [c["name"] for c in _customers(shop.owner, "?search=0712 345").json()["results"]] == [
        "Mama Mboga"
    ]
    assert [c["name"] for c in _customers(shop.owner, "?search=bara").json()["results"]] == [
        "Baraka Otieno"
    ]
    _on_credit(shop, 160)
    owing = _customers(shop.owner, "?has_balance=true").json()["results"]
    assert [(c["name"], c["account"]["balance"]) for c in owing] == [("Mama Mboga", "160.0000")]


# --- Payments -------------------------------------------------------------------------------------


def test_a_payment_reduces_the_balance_and_overpaying_is_refused(shop):
    _on_credit(shop, 240)
    over = _pay(shop, shop.cashier, "300")
    assert over.status_code == 422
    assert over.json()["code"] == "PAYMENT_EXCEEDS_BALANCE"
    assert over.json()["errors"][0]["meta"] == {"balance": "240.00"}

    paid = _pay(shop, shop.cashier, "100", tendered="200")
    assert paid.status_code == 201, paid.json()
    entry = paid.json()
    assert (entry["entry_type"], entry["amount"], entry["balance_after"]) == (
        "PAYMENT",
        "-100.0000",
        "140.0000",
    )
    assert _balance(shop) == 140
    payment = Payment.objects.for_org(shop.organization).get(purpose="ACCOUNT_SETTLEMENT")
    assert (payment.amount, payment.tendered) == (100, 200)


def test_mpesa_payments_need_an_unused_code(shop):
    _on_credit(shop, 240)
    assert _pay(shop, shop.cashier, "100", method=shop.mpesa).status_code == 400
    assert (
        _pay(shop, shop.cashier, "100", method=shop.mpesa, reference="QA12BC34DE").status_code
        == 201
    )
    again = _pay(shop, shop.cashier, "100", method=shop.mpesa, reference="qa12bc34de")
    assert again.json()["code"] == "PAYMENT_REFERENCE_USED"


def test_a_resent_payment_is_recorded_once(shop):
    _on_credit(shop, 240)
    txn = str(uuid.uuid4())
    first = _pay(shop, shop.cashier, "100", txn=txn)
    resent = _pay(shop, shop.cashier, "100", txn=txn)
    assert resent.status_code == 200
    assert resent.json()["id"] == first.json()["id"]
    assert _balance(shop) == 140


def test_payments_only_at_stores_you_work_at(shop):
    _on_credit(shop, 240)
    response = shop.cashier.post(
        f"/api/v1/customers/{shop.customer.pk}/payments/",
        {
            "client_txn_id": str(uuid.uuid4()),
            "store_id": str(shop.branch.pk),
            "payment_method_id": str(shop.cash.pk),
            "amount": "50",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert response.status_code == 400
    assert "store_id" in str(response.json())


# --- Ledger ---------------------------------------------------------------------------------------


def test_the_ledger_lists_every_change_with_the_balance_after(shop):
    _on_credit(shop, 240)
    _pay(shop, shop.cashier, "100")
    entries = shop.cashier.get(f"/api/v1/customers/{shop.customer.pk}/ledger/").json()["results"]
    assert [(e["entry_type"], e["amount"], e["balance_after"]) for e in entries] == [
        ("PAYMENT", "-100.0000", "140.0000"),
        ("CREDIT_SALE", "240.0000", "240.0000"),
    ]
    assert entries[1]["receipt_number"].startswith("MAIN-")


def test_a_mistaken_payment_can_be_reversed_once(shop):
    _on_credit(shop, 240)
    entry = _pay(shop, shop.cashier, "100").json()
    url = f"/api/v1/customers/{shop.customer.pk}/ledger/{entry['id']}/reverse/"

    def reverse(client, reason="Wrong customer"):
        return client.post(
            url, {"reason": reason}, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
        )

    assert reverse(shop.cashier).status_code == 403
    reversal = reverse(shop.owner)
    assert reversal.status_code == 201, reversal.json()
    assert (reversal.json()["amount"], reversal.json()["balance_after"]) == ("100.0000", "240.0000")
    assert Payment.objects.for_org(shop.organization).get(purpose="ACCOUNT_SETTLEMENT").status == (
        "REVERSED"
    )
    assert reverse(shop.owner).status_code == 422
    assert AuditLog.objects.filter(action="customer.entry_reversed").count() == 1

    sale_entry = CustomerLedgerEntry.objects.for_org(shop.organization).get(
        entry_type="CREDIT_SALE"
    )
    refused = shop.owner.post(
        f"/api/v1/customers/{shop.customer.pk}/ledger/{sale_entry.pk}/reverse/",
        {"reason": "Undo"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert refused.status_code == 422


def test_opening_balance_comes_first_and_once(shop):
    url = f"/api/v1/customers/{shop.customer.pk}/account/opening-balance/"

    def opening(amount):
        return shop.owner.post(
            url, {"amount": amount}, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
        )

    assert opening("350").status_code == 201
    assert _balance(shop) == 350
    assert opening("10").status_code == 422


def test_the_account_can_be_frozen_and_not_closed_while_owing(shop):
    url = f"/api/v1/customers/{shop.customer.pk}/account/"
    frozen = shop.owner.patch(url, {"version": 1, "status": "FROZEN"}, format="json")
    assert frozen.json()["status"] == "FROZEN"
    shop.owner.patch(url, {"version": 2, "status": "ACTIVE"}, format="json")
    _on_credit(shop, 80)
    closed = shop.owner.patch(url, {"version": 3, "status": "CLOSED"}, format="json")
    assert closed.status_code == 422
    assert (
        shop.manager.patch(url, {"version": 3, "credit_limit": "50"}, format="json").status_code
        == 403
    )


def test_ledger_entries_are_append_only(shop):
    _on_credit(shop, 80)
    entry = CustomerLedgerEntry.objects.for_org(shop.organization).get()
    with pytest.raises(AppendOnlyError):
        entry.save()
    with pytest.raises(Exception, match="append-only"), transaction.atomic():
        CustomerLedgerEntry.unscoped.filter(pk=entry.pk).update(amount=Decimal(1))
