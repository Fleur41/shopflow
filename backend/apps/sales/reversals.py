"""Voids and returns (docs/ARCHITECTURE.md §6.2, Q-8). Nothing is deleted: a void
marks the sale and writes the opposite of everything it did; a return is its
own document against the sale's lines.

- **Void:** the whole sale, the same business day, while its till session is
  still open, if nothing has been returned from it. Stock comes back, money
  goes back the way it came, credit comes off the customer's account.
- **Return:** some or all of the items, any time. Each line can go back on
  the shelf or not (damaged); the refund is paid out (cash from the till,
  M-Pesa...) or taken off the customer's account.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status

from apps.audit.services import record_audit
from apps.cash.models import CashSession
from apps.cash.services import expected_cash, session_for_cash
from apps.common.currency import minor_units
from apps.common.errors import ApplicationError
from apps.customers import services as customers
from apps.inventory.services import MovementLine, apply_movements, check_quantity
from apps.organizations.context import RequestContext
from apps.organizations.models import Store
from apps.organizations.sequences import next_number
from apps.payments.models import Payment, PaymentMethod

from .models import Sale, SaleItem, SaleReturn, SaleReturnItem


class ReversalRefused(ApplicationError):
    code = "BUSINESS_RULE_VIOLATION"
    title = "This can't be undone that way"


class ReturnExceedsSold(ApplicationError):
    code = "RETURN_EXCEEDS_SOLD"
    title = "More than was sold"


class ReversalInvalid(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"
    title = "Invalid request"


def _invalid(pointer: str, code: str, detail: str) -> ReversalInvalid:
    return ReversalInvalid(
        "One or more fields are invalid.",
        errors=[{"pointer": pointer, "code": code, "detail": detail}],
    )


def _locked_sale(ctx: RequestContext, sale: Sale) -> Sale:
    return (
        Sale.objects.for_org(ctx.organization)
        .select_for_update(of=("self",))
        .select_related("store", "customer", "cash_session")
        .get(pk=sale.pk)
    )


# --- Void -----------------------------------------------------------------------------------------


def void_sale(ctx: RequestContext, sale: Sale, *, reason: str, at: datetime | None = None) -> Sale:
    now = at or timezone.now()
    if not reason.strip():
        raise _invalid("/reason", "REQUIRED", "Say why the sale is being voided.")
    with transaction.atomic():
        sale = _locked_sale(ctx, sale)
        store = sale.store
        if sale.status == Sale.Status.VOIDED:
            raise ReversalRefused("This sale is already voided.")
        local = ZoneInfo(store.timezone)
        if sale.occurred_at.astimezone(local).date() != now.astimezone(local).date():
            raise ReversalRefused(
                "Only today's sales can be voided. Process a return instead.", code="VOID_TOO_LATE"
            )
        if sale.cash_session and sale.cash_session.status != CashSession.Status.OPEN:
            raise ReversalRefused(
                "The till this sale was rung up on has been closed. Process a return instead.",
                code="VOID_TOO_LATE",
            )
        if SaleReturn.objects.for_org(ctx.organization).filter(sale=sale).exists():
            raise ReversalRefused("Items from this sale were returned, so it can't be voided.")

        items = list(
            SaleItem.objects.for_org(ctx.organization).filter(sale=sale).select_related("product")
        )
        apply_movements(
            ctx,
            store,
            [
                MovementLine(
                    product=item.product,
                    quantity=item.quantity,
                    movement_type="SALE_RETURN",
                    source={"sale_item": item},
                )
                for item in items
                if item.product.track_inventory
            ],
            occurred_at=now,
        )
        paid = Payment.objects.for_org(ctx.organization).filter(
            sale=sale, direction=Payment.Direction.IN, status=Payment.Status.CONFIRMED
        )
        Payment.unscoped.bulk_create(
            [
                Payment(
                    organization=ctx.organization,
                    store=store,
                    payment_method_id=payment.payment_method_id,
                    purpose=Payment.Purpose.SALE_REFUND,
                    direction=Payment.Direction.OUT,
                    amount=payment.amount,
                    currency=payment.currency,
                    position=payment.position,
                    received_by=ctx.user,
                    occurred_at=now,
                    sale=sale,
                    cash_session=payment.cash_session,
                )
                for payment in paid
            ]
        )
        if sale.amount_on_credit > 0 and sale.customer:
            customers.credit_back(
                ctx,
                store,
                sale.customer,
                sale.amount_on_credit,
                description=f"Void of sale {sale.receipt_number}",
                sale=sale,
            )
        sale.status = Sale.Status.VOIDED
        sale.voided_at = now
        sale.voided_by = ctx.user
        sale.void_reason = reason.strip()
        sale.save(update_fields=["status", "voided_at", "voided_by", "void_reason", "updated_at"])
        record_audit(
            ctx.audit_actor,
            action="sale.voided",
            entity_type="sale",
            entity_id=sale.pk,
            store_id=store.pk,
            reason=sale.void_reason,
            changes={"status": ["COMPLETED", "VOIDED"], "total": [str(sale.total), None]},
        )
    return sale


# --- Returns ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnLine:
    sale_item: SaleItem
    quantity: Decimal
    restock: bool = True


@dataclass(frozen=True)
class ReturnResult:
    sale_return: SaleReturn
    created: bool


def return_items(
    ctx: RequestContext,
    store: Store,
    sale: Sale,
    *,
    client_txn_id: uuid.UUID,
    reason: str,
    lines: list[ReturnLine],
    refund_to: str,
    payment_method: PaymentMethod | None = None,
    cash_session_id: uuid.UUID | None = None,
) -> ReturnResult:
    if not reason.strip():
        raise _invalid("/reason", "REQUIRED", "Say why the items came back.")
    if not lines:
        raise _invalid("/items", "EMPTY", "Choose what's being returned.")
    refund = SaleReturn.RefundTo(refund_to)
    if refund == SaleReturn.RefundTo.PAYMENT and payment_method is None:
        raise _invalid("/payment_method_id", "REQUIRED", "Choose how the money goes back.")
    with transaction.atomic():
        existing = (
            SaleReturn.objects.for_org(ctx.organization).filter(client_txn_id=client_txn_id).first()
        )
        if existing is not None:
            return ReturnResult(existing, created=False)
        sale = _locked_sale(ctx, sale)
        if sale.status != Sale.Status.COMPLETED:
            raise ReversalRefused("A voided sale has nothing left to return.")
        if refund == SaleReturn.RefundTo.ACCOUNT and sale.customer is None:
            raise _invalid(
                "/refund_to", "NO_CUSTOMER", "This sale has no customer account to refund to."
            )

        places = minor_units(sale.currency)
        quantum = Decimal(1).scaleb(-places)
        amounts = []
        seen = set()
        for index, line in enumerate(lines):
            item = line.sale_item
            pointer = f"/items/{index}"
            if item.sale_id != sale.pk or item.pk in seen:
                raise _invalid(pointer, "INVALID", "Choose each line of this sale once.")
            seen.add(item.pk)
            if line.quantity <= 0:
                raise _invalid(f"{pointer}/quantity", "NOT_POSITIVE", "Enter a quantity above 0.")
            check_quantity(item.product, line.quantity, f"{pointer}/quantity")
            done = (
                SaleReturnItem.objects.for_org(ctx.organization)
                .filter(sale_item=item)
                .aggregate(quantity=Sum("quantity"), amount=Sum("amount"))
            )
            returned = done["quantity"] or Decimal(0)
            refunded = done["amount"] or Decimal(0)
            left = item.quantity - returned
            if line.quantity > left:
                raise ReturnExceedsSold(
                    f"Only {left.normalize():f} of {item.product_name} can still be returned.",
                    errors=[
                        {
                            "pointer": f"{pointer}/quantity",
                            "code": "RETURN_EXCEEDS_SOLD",
                            "meta": {"sold": f"{item.quantity:f}", "returned": f"{returned:f}"},
                        }
                    ],
                )
            if line.quantity == left:  # the last of the line: exactly what's left of its total
                amount = item.line_total - refunded
            else:
                amount = (item.line_total * line.quantity / item.quantity).quantize(
                    quantum, rounding=ROUND_HALF_UP
                )
            amounts.append(amount)
        total = sum(amounts, Decimal(0))

        session = None
        if refund == SaleReturn.RefundTo.PAYMENT and payment_method is not None:
            if not payment_method.is_active:
                raise _invalid(
                    "/payment_method_id", "INACTIVE", f"{payment_method.name} is turned off."
                )
            is_cash = payment_method.kind == PaymentMethod.Kind.CASH
            session = session_for_cash(ctx, store, cash_session_id, takes_cash=is_cash)
            if is_cash and session is not None and total > expected_cash(session):
                raise ReversalRefused(
                    "There isn't enough cash in the till for this refund.", code="NOT_ENOUGH_CASH"
                )

        now = timezone.now()
        sale_return = SaleReturn.objects.create(
            organization=ctx.organization,
            store=store,
            sale=sale,
            return_number=next_number(ctx, store, "RETURN", now, prefix="R"),
            client_txn_id=client_txn_id,
            refund_to=refund,
            currency=sale.currency,
            total=total,
            reason=reason.strip(),
            created_by=ctx.user,
            cash_session=session,
            occurred_at=now,
        )
        restock = []
        for line, amount in zip(lines, amounts, strict=True):
            returned_item = SaleReturnItem.objects.create(
                organization=ctx.organization,
                sale_return=sale_return,
                sale_item=line.sale_item,
                quantity=line.quantity,
                amount=amount,
                restock=line.restock,
            )
            if line.restock and line.sale_item.product.track_inventory:
                restock.append(
                    MovementLine(
                        product=line.sale_item.product,
                        quantity=line.quantity,
                        movement_type="SALE_RETURN",
                        source={"sale_return_item": returned_item},
                    )
                )
        apply_movements(ctx, store, restock, occurred_at=now)

        if total > 0 and refund == SaleReturn.RefundTo.PAYMENT and payment_method is not None:
            Payment.objects.create(
                organization=ctx.organization,
                store=store,
                payment_method=payment_method,
                purpose=Payment.Purpose.SALE_REFUND,
                direction=Payment.Direction.OUT,
                amount=total,
                currency=sale.currency,
                received_by=ctx.user,
                occurred_at=now,
                sale_return=sale_return,
                cash_session=session,
            )
        elif total > 0 and sale.customer is not None:
            customers.credit_back(
                ctx,
                store,
                sale.customer,
                total,
                description=f"Return {sale_return.return_number} (sale {sale.receipt_number})",
                sale_return=sale_return,
            )
        record_audit(
            ctx.audit_actor,
            action="sale.returned",
            entity_type="sale",
            entity_id=sale.pk,
            store_id=store.pk,
            reason=sale_return.reason,
            changes={
                "return_number": [None, sale_return.return_number],
                "total": [None, str(total)],
                "refund_to": [None, refund.value],
            },
        )
    return ReturnResult(sale_return, created=True)
