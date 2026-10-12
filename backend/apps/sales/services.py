"""Completing a sale (docs/API.md §4.5): one transaction that prices the cart,
takes the payments, moves the stock and issues the receipt number.

Order of work inside the transaction:
1. return the earlier sale if this ``client_txn_id`` was already recorded;
2. check every line (active product, quantity, the price the till showed);
3. lock the stock levels (product-id order) and price the cart on the server;
4. check the tenders add up, cash gives change, references are present and unused;
5. write the sale, its lines and payments, move stock, issue the number, audit.
Any failure rolls back all of it (invariant 15).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status

from apps.audit.services import record_audit
from apps.cash.services import session_for_cash
from apps.catalog.models import Product
from apps.common.currency import minor_units
from apps.common.errors import ApplicationError
from apps.inventory import selectors as inventory_selectors
from apps.inventory.services import MovementLine, apply_movements, check_quantity, lock_levels
from apps.organizations.access import require_permission
from apps.organizations.context import RequestContext
from apps.organizations.models import Store
from apps.organizations.sequences import next_number
from apps.payments.models import Payment, PaymentMethod
from apps.payments.providers import PaymentRequest, PaymentStatus, get_provider

from .models import Sale, SaleItem
from .pricing import LineInput, PricingError, price_cart

MAX_ITEMS = 300
CLOCK_SKEW = timedelta(minutes=5)

PRICING_MESSAGES = {
    "LINE_DISCOUNT_EXCEEDS_LINE": "The discount is more than the line is worth.",
    "ORDER_DISCOUNT_EXCEEDS_TOTAL": "The discount is more than the sale is worth.",
    "TOO_MANY_DECIMALS": "Too many decimal places.",
    "QUANTITY_NOT_POSITIVE": "Enter a quantity above 0.",
}


class PriceChanged(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    code = "PRICE_CHANGED"
    title = "Prices have changed"


class ProductInactive(ApplicationError):
    code = "PRODUCT_INACTIVE"
    title = "Product no longer sold"


class SaleRejected(ApplicationError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "BUSINESS_RULE_VIOLATION"
    title = "The sale could not be completed"


class SaleInvalid(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"
    title = "Invalid request"


@dataclass(frozen=True)
class ItemInput:
    product: Product
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = Decimal(0)
    price_override: bool = False
    override_reason: str = ""
    scanned_code: str = ""


@dataclass(frozen=True)
class TenderInput:
    payment_method: PaymentMethod
    amount: Decimal
    tendered: Decimal | None = None
    reference: str = ""


@dataclass
class SaleRequest:
    client_txn_id: uuid.UUID
    items: list[ItemInput]
    tenders: list[TenderInput]
    occurred_at: datetime | None = None
    order_discount: Decimal = Decimal(0)
    credit_amount: Decimal = Decimal(0)
    customer: Any = None  # apps.customers.models.Customer (Phase 4.3)
    notes: str = ""
    origin: str = Sale.Origin.WEB
    cash_session_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SaleResult:
    sale: Sale
    created: bool


# Credit sales are charged to the customer's account by the customers app, which
# registers itself here so this module doesn't import it (it imports sales).
CreditCharger = Callable[[RequestContext, Store, Any, Sale, Decimal], object]
_credit_charger: list[CreditCharger] = []


def register_credit_charger(charger: CreditCharger) -> None:
    _credit_charger[:] = [charger]


def create_sale(ctx: RequestContext, store: Store, request: SaleRequest) -> SaleResult:
    now = timezone.now()
    occurred_at = request.occurred_at or now
    if occurred_at > now + CLOCK_SKEW:
        raise _invalid("/occurred_at", "IN_FUTURE", "The sale's time is in the future.")
    if not request.items:
        raise _invalid("/items", "EMPTY", "Add at least one item.")
    if len(request.items) > MAX_ITEMS:
        raise _invalid("/items", "TOO_MANY", f"At most {MAX_ITEMS} lines in one sale.")

    with transaction.atomic():
        existing = (
            Sale.objects.for_org(ctx.organization)
            .filter(client_txn_id=request.client_txn_id)
            .first()
        )
        if existing is not None:
            return SaleResult(existing, created=False)

        _check_items(ctx, request)
        stocked = [item.product.pk for item in request.items if item.product.track_inventory]
        levels = lock_levels(ctx, store, stocked)
        list_prices = _check_prices(ctx, store, request, levels)

        currency = store.currency
        places = minor_units(currency)
        priced = _price(ctx, request, places)
        total = Decimal(priced.total)
        _check_credit(ctx, request, total)
        payments, change = _check_tenders(ctx, request, total, places, currency)
        takes_cash = any(t.payment_method.kind == PaymentMethod.Kind.CASH for t in request.tenders)
        session = session_for_cash(ctx, store, request.cash_session_id, takes_cash=takes_cash)

        sale = Sale.objects.create(
            organization=ctx.organization,
            store=store,
            receipt_number=next_number(ctx, store, "SALE", occurred_at),
            client_txn_id=request.client_txn_id,
            cashier=ctx.user,
            customer=request.customer,
            currency=currency,
            tax_mode=ctx.organization.tax_mode,
            subtotal=Decimal(priced.subtotal),
            discount_total=Decimal(priced.discount_total),
            tax_total=Decimal(priced.tax_total),
            total=total,
            amount_paid=total - request.credit_amount,
            amount_on_credit=request.credit_amount,
            change_given=change,
            origin=request.origin,
            notes=request.notes.strip(),
            cash_session=session,
            occurred_at=occurred_at,
        )
        movements = []
        for index, (item, line) in enumerate(zip(request.items, priced.lines, strict=True)):
            level = levels.get(item.product.pk)
            sale_item = SaleItem.objects.create(
                organization=ctx.organization,
                sale=sale,
                line_no=index + 1,
                product=item.product,
                product_name=item.product.name,
                sku=item.product.sku,
                unit_code=item.product.unit.code,
                scanned_code=item.scanned_code,
                quantity=item.quantity,
                unit_price=item.unit_price,
                list_price=list_prices[index],
                price_overridden=item.unit_price != list_prices[index],
                override_reason=item.override_reason.strip(),
                unit_cost=(level.average_cost if level else None) or item.product.default_cost,
                discount_amount=Decimal(line.discount_amount),
                order_discount_share=Decimal(line.order_discount),
                tax_rate=item.product.tax_rate.rate,
                tax_name=item.product.tax_rate.name,
                tax_amount=Decimal(line.tax_amount),
                line_total=Decimal(line.line_total),
            )
            if item.product.track_inventory:
                movements.append(
                    MovementLine(
                        product=item.product,
                        quantity=-item.quantity,
                        movement_type="SALE",
                        source={"sale_item": sale_item},
                        pointer=f"/items/{index}/quantity",
                    )
                )
        apply_movements(ctx, store, movements, occurred_at=occurred_at)

        for payment in payments:
            payment.sale = sale
            payment.store = store
            payment.cash_session = session
            payment.occurred_at = occurred_at
        try:
            with transaction.atomic():
                Payment.unscoped.bulk_create(payments)
        except IntegrityError as exc:  # the same reference confirmed a moment ago
            raise _reference_used(None) from exc

        if request.credit_amount > 0:
            _credit_charger[0](ctx, store, request.customer, sale, request.credit_amount)

        record_audit(
            ctx.audit_actor,
            action="sale.completed",
            entity_type="sale",
            entity_id=sale.pk,
            store_id=store.pk,
            changes={
                "receipt_number": [None, sale.receipt_number],
                "total": [None, str(sale.total)],
                "lines": [None, len(request.items)],
                "price_overrides": [
                    None,
                    sum(
                        1
                        for i, item in enumerate(request.items)
                        if item.unit_price != list_prices[i]
                    ),
                ],
            },
        )
    return SaleResult(sale, created=True)


# --- Checks -------------------------------------------------------------------------------


def _check_items(ctx: RequestContext, request: SaleRequest) -> None:
    for index, item in enumerate(request.items):
        pointer = f"/items/{index}"
        if not item.product.is_active:
            raise ProductInactive(
                f"{item.product.name} is no longer sold. Remove it from the sale.",
                errors=[{"pointer": pointer, "code": "PRODUCT_INACTIVE"}],
            )
        if item.quantity <= 0:
            raise _invalid(f"{pointer}/quantity", "NOT_POSITIVE", "Enter a quantity above 0.")
        check_quantity(item.product, item.quantity, f"{pointer}/quantity")
    if request.order_discount > 0 or any(item.discount_amount > 0 for item in request.items):
        require_permission(ctx, "sales.discount")


def _check_prices(
    ctx: RequestContext, store: Store, request: SaleRequest, levels: dict[uuid.UUID, Any]
) -> list[Decimal]:
    """The store's price for each line. A line priced differently is a stale till
    (409, with the current prices) unless it is a deliberate, permitted override."""
    list_prices = []
    stale: list[dict[str, Any]] = []
    for index, item in enumerate(request.items):
        price = inventory_selectors.effective_price(item.product, levels.get(item.product.pk))
        list_prices.append(price)
        if item.unit_price == price:
            continue
        if item.price_override:
            require_permission(ctx, "sales.override_price")
            if not item.override_reason.strip():
                raise _invalid(
                    f"/items/{index}/override_reason", "REQUIRED", "Say why the price changed."
                )
            continue
        stale.append(
            {
                "pointer": f"/items/{index}/unit_price",
                "code": "PRICE_CHANGED",
                "meta": {
                    "product_id": str(item.product.pk),
                    "product_name": item.product.name,
                    "shown": f"{item.unit_price:.4f}",
                    "current": f"{price:.4f}",
                },
            }
        )
    if stale:
        names = ", ".join(e["meta"]["product_name"] for e in stale)
        raise PriceChanged(
            f"The price of {names} changed. Check the new prices with the customer.",
            errors=stale,
        )
    return list_prices


def _price(ctx: RequestContext, request: SaleRequest, places: int) -> Any:
    lines = [
        LineInput(
            quantity=f"{item.quantity:f}",
            unit_price=f"{item.unit_price:f}",
            tax_rate=f"{item.product.tax_rate.rate:f}",
            discount_amount=_plain(item.discount_amount),
        )
        for item in request.items
    ]
    try:
        return price_cart(
            lines,
            minor_units=places,
            tax_mode=ctx.organization.tax_mode,
            order_discount=_plain(request.order_discount),
        )
    except PricingError as exc:
        if exc.line is None:
            pointer = "/order_discount"
        elif exc.code == "TOO_MANY_DECIMALS":
            pointer = f"/items/{exc.line}"
        else:
            pointer = f"/items/{exc.line}/discount_amount"
        raise _invalid(
            pointer, exc.code, PRICING_MESSAGES.get(exc.code, "Invalid amount.")
        ) from exc


def _plain(amount: Decimal) -> str:
    """``Decimal("10.0000")`` → ``"10"``: the API pads to 4 places, but the
    pricing engine rejects more places than the currency has."""
    return f"{amount.normalize():f}"


def _check_credit(ctx: RequestContext, request: SaleRequest, total: Decimal) -> None:
    if request.credit_amount == 0:
        return
    require_permission(ctx, "sales.credit")
    if request.customer is None:
        raise _invalid("/customer_id", "REQUIRED", "Choose the customer who is buying on credit.")
    if request.credit_amount > total:
        raise _invalid("/credit_amount", "TOO_LARGE", "Credit can't be more than the sale.")
    if not _credit_charger:  # pragma: no cover - the customers app registers one
        raise SaleRejected("Credit sales aren't available.")


def _check_tenders(
    ctx: RequestContext, request: SaleRequest, total: Decimal, places: int, currency: str
) -> tuple[list[Payment], Decimal]:
    quantum = Decimal(1).scaleb(-places)
    payments = []
    change = Decimal(0)
    cash_seen = False
    references: set[tuple[uuid.UUID, str]] = set()
    for index, tender in enumerate(request.tenders):
        pointer = f"/tenders/{index}"
        method = tender.payment_method
        if not method.is_active:
            raise _invalid(
                f"{pointer}/payment_method_id", "INACTIVE", f"{method.name} is turned off."
            )
        if tender.amount <= 0 or tender.amount != tender.amount.quantize(quantum):
            raise _invalid(f"{pointer}/amount", "INVALID", "Enter an amount above 0.")
        reference = tender.reference.strip().upper()
        if method.requires_reference and not reference:
            raise _invalid(
                f"{pointer}/reference", "REQUIRED", f"Enter the {method.name} transaction code."
            )
        tendered = None
        if method.kind == PaymentMethod.Kind.CASH:
            if cash_seen:
                raise _invalid(pointer, "DUPLICATE_CASH", "Enter cash once.")
            cash_seen = True
            tendered = tender.tendered if tender.tendered is not None else tender.amount
            if tendered < tender.amount:
                raise _invalid(
                    f"{pointer}/tendered", "TOO_LITTLE", "The cash given is less than the amount."
                )
            change = tendered - tender.amount
        elif tender.tendered is not None and tender.tendered != tender.amount:
            raise _invalid(
                f"{pointer}/tendered", "NOT_CASH", f"Only cash gives change, not {method.name}."
            )
        if reference:
            if (method.pk, reference) in references or _reference_taken(ctx, method, reference):
                raise _reference_used(f"{pointer}/reference", method, reference)
            references.add((method.pk, reference))
        outcome = get_provider(method.provider).initiate(
            PaymentRequest(amount=tender.amount, currency=currency, reference=reference)
        )
        if outcome.status != PaymentStatus.CONFIRMED:  # pragma: no cover - async providers later
            raise SaleRejected(outcome.message or f"{method.name} payment was not confirmed.")
        payments.append(
            Payment(
                organization=ctx.organization,
                payment_method=method,
                purpose=Payment.Purpose.SALE,
                amount=tender.amount,
                currency=currency,
                tendered=tendered,
                external_reference=reference,
                position=index,
                received_by=ctx.user,
            )
        )
    paid = sum((t.amount for t in request.tenders), Decimal(0))
    if paid + request.credit_amount != total:
        short = total - paid - request.credit_amount
        raise SaleRejected(
            f"The payments come to {paid + request.credit_amount:.{places}f}, but the sale is "
            f"{total:.{places}f}." + (f" {short:.{places}f} still to pay." if short > 0 else ""),
            code="TENDERS_DO_NOT_MATCH_TOTAL",
            errors=[
                {
                    "pointer": "/tenders",
                    "code": "TENDERS_DO_NOT_MATCH_TOTAL",
                    "meta": {"total": f"{total:.{places}f}", "paid": f"{paid:.{places}f}"},
                }
            ],
        )
    return payments, change


def _reference_taken(ctx: RequestContext, method: PaymentMethod, reference: str) -> bool:
    return (
        Payment.objects.for_org(ctx.organization)
        .filter(
            payment_method=method,
            external_reference=reference,
            direction=Payment.Direction.IN,
            status__in=[Payment.Status.PENDING, Payment.Status.CONFIRMED],
        )
        .exists()
    )


def _reference_used(
    pointer: str | None, method: PaymentMethod | None = None, reference: str = ""
) -> SaleRejected:
    what = f"{method.name} code {reference}" if method else "This payment reference"
    return SaleRejected(
        f"{what} has already been used for another payment. Check the customer's message.",
        code="PAYMENT_REFERENCE_USED",
        errors=[{"pointer": pointer or "/tenders", "code": "PAYMENT_REFERENCE_USED"}],
    )


def _invalid(pointer: str, code: str, detail: str) -> SaleInvalid:
    return SaleInvalid(
        "One or more fields are invalid.",
        errors=[{"pointer": pointer, "code": code, "detail": detail}],
    )
