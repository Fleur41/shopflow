"""Customer accounts: credit sales, payments, opening balances and reversals.

Every balance change goes through ``_post``, which locks the account, numbers
the entry and records the balance after it, in the caller's transaction.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status

from apps.audit.services import record_audit
from apps.cash.services import session_for_cash
from apps.common.currency import minor_units
from apps.common.errors import ApplicationError, StaleVersion
from apps.organizations import master_data
from apps.organizations.access import require_permission
from apps.organizations.context import RequestContext
from apps.organizations.models import Store
from apps.payments.models import Payment, PaymentMethod
from apps.sales import services as sales_services
from apps.sales.models import Sale

from .models import Customer, CustomerAccount, CustomerLedgerEntry


class CreditLimitExceeded(ApplicationError):
    code = "CREDIT_LIMIT_EXCEEDED"
    title = "Over the credit limit"


class CustomerFrozen(ApplicationError):
    code = "CUSTOMER_FROZEN"
    title = "Account frozen"


class PaymentExceedsBalance(ApplicationError):
    code = "PAYMENT_EXCEEDS_BALANCE"
    title = "More than the customer owes"


class LedgerRuleViolation(ApplicationError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "BUSINESS_RULE_VIOLATION"
    title = "The account change could not be made"


def _money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount:,.{minor_units(currency)}f}"


# --- Customers ------------------------------------------------------------------------------


def create_customer(
    ctx: RequestContext, *, credit_limit: Decimal | None = None, **fields: Any
) -> Customer:
    """A customer and their account in the business's currency."""
    if credit_limit is not None:
        require_permission(ctx, "customers.set_credit_limit")
    with transaction.atomic():
        customer = master_data.create_entry(ctx, Customer, **fields)
        CustomerAccount.objects.create(
            organization=ctx.organization,
            customer=customer,
            currency=ctx.organization.base_currency,
            credit_limit=credit_limit,
        )
    return customer


def account_of(ctx: RequestContext, customer: Customer, *, lock: bool = False) -> CustomerAccount:
    accounts = CustomerAccount.objects.for_org(ctx.organization).filter(
        customer=customer, currency=ctx.organization.base_currency
    )
    if lock:
        accounts = accounts.select_for_update()
    account = accounts.first()
    if account is None:  # customers made before accounts existed, or another currency
        CustomerAccount.unscoped.bulk_create(
            [
                CustomerAccount(
                    organization=ctx.organization,
                    customer=customer,
                    currency=ctx.organization.base_currency,
                )
            ],
            ignore_conflicts=True,
        )
        account = accounts.get()
    return account


def update_account(
    ctx: RequestContext, customer: Customer, *, version: int, **changes: Any
) -> CustomerAccount:
    """Set the credit limit or freeze/unfreeze the account. Audited."""
    require_permission(ctx, "customers.set_credit_limit")
    with transaction.atomic():
        account = account_of(ctx, customer, lock=True)
        if account.version != version:
            raise StaleVersion("Someone else changed this. Reload and try again.")
        if changes.get("status") == CustomerAccount.Status.CLOSED and account.balance > 0:
            raise LedgerRuleViolation(
                "This customer still owes money. Settle the balance before closing the account."
            )
        before = {name: getattr(account, name) for name in changes}
        for name, value in changes.items():
            setattr(account, name, value)
        changed = {
            name: [_jsonable(before[name]), _jsonable(value)]
            for name, value in changes.items()
            if before[name] != value
        }
        if changed:
            account.version += 1
            account.save(update_fields=[*changes, "version", "updated_at"])
            record_audit(
                ctx.audit_actor,
                action="customer_account.updated",
                entity_type="customer",
                entity_id=customer.pk,
                changes=changed,
            )
    return account


def _jsonable(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


# --- Ledger ------------------------------------------------------------------------------------


def _post(
    ctx: RequestContext,
    account: CustomerAccount,
    *,
    entry_type: str,
    amount: Decimal,
    store: Store | None,
    occurred_at: datetime,
    description: str = "",
    **source: Any,
) -> CustomerLedgerEntry:
    """Append an entry to a locked account and move its balance."""
    balance = account.balance + amount
    if balance < 0:
        raise PaymentExceedsBalance(
            f"That's more than the customer owes ({_money(account.balance, account.currency)}).",
            errors=[
                {
                    "pointer": "/amount",
                    "code": "PAYMENT_EXCEEDS_BALANCE",
                    "meta": {"balance": f"{account.balance:.{minor_units(account.currency)}f}"},
                }
            ],
        )
    account.balance = balance
    account.last_entry_seq += 1
    account.save(update_fields=["balance", "last_entry_seq", "updated_at"])
    return CustomerLedgerEntry.objects.create(
        organization=ctx.organization,
        account=account,
        store=store,
        seq=account.last_entry_seq,
        entry_type=entry_type,
        amount=amount,
        balance_after=balance,
        description=description,
        created_by=ctx.user,
        occurred_at=occurred_at,
        **source,
    )


def charge_credit_sale(
    ctx: RequestContext, store: Store, customer: Customer, sale: Sale, amount: Decimal
) -> CustomerLedgerEntry:
    """Put part of a sale on the customer's account, within their credit limit
    (or beyond it, with ``customers.exceed_credit_limit``)."""
    if not customer.is_active:
        raise LedgerRuleViolation(f"{customer.name} is deactivated.")
    account = account_of(ctx, customer, lock=True)
    if account.status != CustomerAccount.Status.ACTIVE:
        raise CustomerFrozen(
            f"{customer.name}'s account is {account.status.lower()}: no new credit.",
            errors=[{"pointer": "/customer_id", "code": "CUSTOMER_FROZEN"}],
        )
    limit = account.credit_limit or Decimal(0)
    available = max(limit - account.balance, Decimal(0))
    if amount > available and not ctx.has_perm("customers.exceed_credit_limit"):
        places = minor_units(account.currency)
        raise CreditLimitExceeded(
            f"{customer.name} can take {_money(available, account.currency)} more on credit "
            f"(limit {_money(limit, account.currency)}, owing "
            f"{_money(account.balance, account.currency)}).",
            errors=[
                {
                    "pointer": "/credit_amount",
                    "code": "CREDIT_LIMIT_EXCEEDED",
                    "meta": {
                        "credit_limit": f"{limit:.{places}f}",
                        "balance": f"{account.balance:.{places}f}",
                        "available": f"{available:.{places}f}",
                    },
                }
            ],
        )
    if amount > available:
        require_permission(ctx, "customers.exceed_credit_limit")  # MFA for the override
    return _post(
        ctx,
        account,
        entry_type=CustomerLedgerEntry.Type.CREDIT_SALE,
        amount=amount,
        store=store,
        occurred_at=sale.occurred_at,
        description=f"Sale {sale.receipt_number}",
        sale=sale,
    )


sales_services.register_credit_charger(charge_credit_sale)


def credit_back(
    ctx: RequestContext,
    store: Store,
    customer: Customer,
    amount: Decimal,
    *,
    description: str,
    **source: Any,
) -> CustomerLedgerEntry:
    """Take ``amount`` off what a customer owes, for a voided sale (``sale=``) or a
    return (``sale_return=``). Never below zero (Q-6): a customer who has already
    paid gets money back instead."""
    account = account_of(ctx, customer, lock=True)
    if amount > account.balance:
        raise LedgerRuleViolation(
            f"{customer.name} only owes {_money(account.balance, account.currency)}, so "
            f"{_money(amount, account.currency)} can't come off their account. "
            "Pay the difference back instead.",
            code="REFUND_EXCEEDS_BALANCE",
            errors=[
                {
                    "pointer": "/refund_to",
                    "code": "REFUND_EXCEEDS_BALANCE",
                    "meta": {"balance": f"{account.balance:.{minor_units(account.currency)}f}"},
                }
            ],
        )
    return _post(
        ctx,
        account,
        entry_type=CustomerLedgerEntry.Type.SALE_RETURN,
        amount=-amount,
        store=store,
        occurred_at=timezone.now(),
        description=description,
        **source,
    )


def receive_payment(
    ctx: RequestContext,
    customer: Customer,
    *,
    store: Store,
    client_txn_id: uuid.UUID,
    amount: Decimal,
    payment_method: PaymentMethod,
    reference: str = "",
    tendered: Decimal | None = None,
    occurred_at: datetime | None = None,
    cash_session_id: uuid.UUID | None = None,
) -> tuple[CustomerLedgerEntry, bool]:
    """Record money a customer paid towards their balance. Returns the ledger
    entry and whether it was created now (``False`` for a resent request)."""
    occurred_at = occurred_at or timezone.now()
    reference = reference.strip().upper()
    with transaction.atomic():
        existing = (
            CustomerLedgerEntry.objects.for_org(ctx.organization)
            .filter(payment__client_txn_id=client_txn_id)
            .first()
        )
        if existing is not None:
            return existing, False
        account = account_of(ctx, customer, lock=True)
        places = minor_units(account.currency)
        if amount <= 0 or amount != amount.quantize(Decimal(1).scaleb(-places)):
            raise LedgerRuleViolation(
                "Enter an amount above 0.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="VALIDATION_ERROR",
                errors=[{"pointer": "/amount", "code": "INVALID"}],
            )
        if not payment_method.is_active:
            raise LedgerRuleViolation(f"{payment_method.name} is turned off.")
        if payment_method.requires_reference and not reference:
            raise LedgerRuleViolation(
                f"Enter the {payment_method.name} transaction code.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="VALIDATION_ERROR",
                errors=[{"pointer": "/reference", "code": "REQUIRED"}],
            )
        if payment_method.kind != PaymentMethod.Kind.CASH:
            tendered = None
        elif tendered is not None and tendered < amount:
            raise LedgerRuleViolation(
                "The cash given is less than the amount.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="VALIDATION_ERROR",
                errors=[{"pointer": "/tendered", "code": "TOO_LITTLE"}],
            )
        is_cash = payment_method.kind == PaymentMethod.Kind.CASH
        session = session_for_cash(ctx, store, cash_session_id, takes_cash=is_cash)
        try:
            with transaction.atomic():
                payment = Payment.objects.create(
                    organization=ctx.organization,
                    store=store,
                    cash_session=session,
                    payment_method=payment_method,
                    purpose=Payment.Purpose.ACCOUNT_SETTLEMENT,
                    amount=amount,
                    currency=account.currency,
                    tendered=tendered,
                    external_reference=reference,
                    client_txn_id=client_txn_id,
                    received_by=ctx.user,
                    occurred_at=occurred_at,
                    customer_account=account,
                )
        except IntegrityError as exc:
            raise LedgerRuleViolation(
                f"{payment_method.name} code {reference} has already been used for another "
                "payment. Check the customer's message.",
                code="PAYMENT_REFERENCE_USED",
                errors=[{"pointer": "/reference", "code": "PAYMENT_REFERENCE_USED"}],
            ) from exc
        entry = _post(
            ctx,
            account,
            entry_type=CustomerLedgerEntry.Type.PAYMENT,
            amount=-amount,
            store=store,
            occurred_at=occurred_at,
            description=f"{payment_method.name} {reference}".strip(),
            payment=payment,
        )
        record_audit(
            ctx.audit_actor,
            action="customer.payment_received",
            entity_type="customer",
            entity_id=customer.pk,
            store_id=store.pk,
            changes={"amount": [None, str(amount)], "balance": [None, str(entry.balance_after)]},
        )
    return entry, True


def set_opening_balance(
    ctx: RequestContext, customer: Customer, *, amount: Decimal, note: str = ""
) -> CustomerLedgerEntry:
    """What a customer already owed when the business started using ShopFlow."""
    with transaction.atomic():
        account = account_of(ctx, customer, lock=True)
        if account.last_entry_seq:
            raise LedgerRuleViolation(
                "This account already has entries; an opening balance must come first."
            )
        if amount <= 0:
            raise LedgerRuleViolation("Enter what the customer owes, above 0.")
        entry = _post(
            ctx,
            account,
            entry_type=CustomerLedgerEntry.Type.OPENING_BALANCE,
            amount=amount,
            store=None,
            occurred_at=timezone.now(),
            description=note.strip() or "Opening balance",
        )
        record_audit(
            ctx.audit_actor,
            action="customer.opening_balance",
            entity_type="customer",
            entity_id=customer.pk,
            changes={"amount": [None, str(amount)]},
        )
    return entry


REVERSIBLE = {CustomerLedgerEntry.Type.PAYMENT, CustomerLedgerEntry.Type.OPENING_BALANCE}


def reverse_entry(
    ctx: RequestContext, entry: CustomerLedgerEntry, *, reason: str
) -> CustomerLedgerEntry:
    """Undo a payment recorded by mistake (or a wrong opening balance) with an
    opposite entry. Credit sales are undone by voiding or returning the sale."""
    if entry.entry_type not in REVERSIBLE:
        raise LedgerRuleViolation(
            "Only payments and opening balances can be reversed here. "
            "Void or return the sale instead."
        )
    if not reason.strip():
        raise LedgerRuleViolation(
            "Say why the entry is being reversed.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            errors=[{"pointer": "/reason", "code": "REQUIRED"}],
        )
    with transaction.atomic():
        account = (
            CustomerAccount.objects.for_org(ctx.organization)
            .select_for_update()
            .get(pk=entry.account_id)
        )
        if CustomerLedgerEntry.objects.for_org(ctx.organization).filter(reverses=entry).exists():
            raise LedgerRuleViolation("This entry has already been reversed.")
        try:
            with transaction.atomic():
                reversal = _post(
                    ctx,
                    account,
                    entry_type=CustomerLedgerEntry.Type.REVERSAL,
                    amount=-entry.amount,
                    store=entry.store,
                    occurred_at=timezone.now(),
                    description=f"Reversal: {reason.strip()}"[:300],
                    reverses=entry,
                )
        except IntegrityError as exc:  # reversed by someone else just now
            raise LedgerRuleViolation("This entry has already been reversed.") from exc
        if entry.payment_id:
            Payment.objects.for_org(ctx.organization).filter(pk=entry.payment_id).update(
                status=Payment.Status.REVERSED
            )
        record_audit(
            ctx.audit_actor,
            action="customer.entry_reversed",
            entity_type="customer",
            entity_id=account.customer_id,
            reason=reason.strip(),
            changes={"entry": [None, str(entry.pk)], "amount": [None, str(reversal.amount)]},
        )
    return reversal
