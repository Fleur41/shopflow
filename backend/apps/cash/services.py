"""Till sessions: open with a float, move cash in and out, close with a blind count.

Expected cash (docs/ARCHITECTURE.md §6.8):

    opening float + cash taken - cash paid back + pay-ins - pay-outs - drops

Cash taken and paid back are the session's confirmed cash payments (sales,
customer payments, refunds); corrections recorded after closing are reported
separately and never change a closed session.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status

from apps.audit.services import record_audit
from apps.common.currency import minor_units
from apps.common.errors import ApplicationError
from apps.organizations.access import require_permission
from apps.organizations.context import RequestContext
from apps.organizations.models import Store
from apps.payments.models import Payment, PaymentMethod

from .models import CashMovement, CashSession, Till


class CashRuleViolation(ApplicationError):
    code = "BUSINESS_RULE_VIOLATION"
    title = "The till change could not be made"


class TillBusy(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    code = "TILL_ALREADY_OPEN"
    title = "Till already open"


class CashSessionRequired(ApplicationError):
    code = "CASH_SESSION_REQUIRED"
    title = "Open the till first"


class CashInvalid(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "VALIDATION_ERROR"
    title = "Invalid request"


def _invalid(pointer: str, code: str, detail: str) -> CashInvalid:
    return CashInvalid(
        "One or more fields are invalid.",
        errors=[{"pointer": pointer, "code": code, "detail": detail}],
    )


def _money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount:,.{minor_units(currency)}f}"


def _check_amount(
    amount: Decimal, currency: str, pointer: str, *, allow_zero: bool = False
) -> None:
    quantum = Decimal(1).scaleb(-minor_units(currency))
    if amount != amount.quantize(quantum) or amount < 0 or (amount == 0 and not allow_zero):
        raise _invalid(pointer, "INVALID", "Enter an amount in the store's currency.")


# --- Opening ---------------------------------------------------------------------------------


def open_session(
    ctx: RequestContext,
    store: Store,
    *,
    till: Till,
    opening_float: Decimal,
    client_txn_id: uuid.UUID,
) -> CashSession:
    """Open ``till``. One open session per till, and per person per store, so the
    till a sale belongs to is never in doubt."""
    _check_amount(opening_float, store.currency, "/opening_float", allow_zero=True)
    with transaction.atomic():
        existing = (
            CashSession.objects.for_org(ctx.organization)
            .filter(client_txn_id=client_txn_id)
            .first()
        )
        if existing is not None:
            return existing
        if till.store_id != store.pk or not till.is_active:
            raise _invalid("/till_id", "INVALID", "Choose an active till in this store.")
        mine = current_session(ctx, store)
        if mine is not None:
            raise TillBusy(
                f"You already have {mine.till.name} open in this store. Close it first.",
                code="SESSION_ALREADY_OPEN",
            )
        try:
            with transaction.atomic():
                session = CashSession.objects.create(
                    organization=ctx.organization,
                    store=store,
                    till=till,
                    client_txn_id=client_txn_id,
                    opened_by=ctx.user,
                    opened_at=timezone.now(),
                    opening_float=opening_float,
                )
        except IntegrityError as exc:
            holder = (
                CashSession.objects.for_org(ctx.organization)
                .filter(till=till, status=CashSession.Status.OPEN)
                .select_related("opened_by")
                .first()
            )
            who = holder.opened_by.full_name if holder else "someone else"
            raise TillBusy(f"{till.name} is already open ({who}).") from exc
        record_audit(
            ctx.audit_actor,
            action="cash_session.opened",
            entity_type="cash_session",
            entity_id=session.pk,
            store_id=store.pk,
            changes={"till": [None, till.name], "opening_float": [None, str(opening_float)]},
        )
    return session


def current_session(ctx: RequestContext, store: Store) -> CashSession | None:
    """The caller's open session in ``store``, if any."""
    return (
        CashSession.objects.for_org(ctx.organization)
        .filter(store=store, opened_by=ctx.user, status=CashSession.Status.OPEN)
        .select_related("till")
        .first()
    )


def session_for_cash(
    ctx: RequestContext,
    store: Store,
    session_id: uuid.UUID | None,
    *,
    takes_cash: bool,
) -> CashSession | None:
    """The open session a sale, refund or payment belongs to, locked so it can't
    close underneath. Cash needs one when the store says so."""
    sessions = CashSession.objects.for_org(ctx.organization).filter(
        store=store, status=CashSession.Status.OPEN
    )
    if session_id is not None:
        session = sessions.filter(pk=session_id).select_for_update().first()
        if session is None:
            raise _invalid("/cash_session_id", "NOT_OPEN", "That till session isn't open.")
    else:
        session = sessions.filter(opened_by=ctx.user).select_for_update().first()
    if session is None and takes_cash and store.require_cash_session:
        raise CashSessionRequired(
            "Open the till before taking or paying out cash.",
            errors=[{"pointer": "/cash_session_id", "code": "CASH_SESSION_REQUIRED"}],
        )
    return session


# --- Pay-ins, pay-outs, drops and corrections -------------------------------------------------


def record_movement(
    ctx: RequestContext,
    session: CashSession,
    *,
    movement_type: str,
    amount: Decimal,
    reason: str,
    client_txn_id: uuid.UUID,
) -> CashMovement:
    """Cash in or out of an open drawer, or a correction to a closed one."""
    kind = CashMovement.Type(movement_type)
    if kind == CashMovement.Type.CORRECTION:
        require_permission(ctx, "cash.correct")
        if amount == 0:
            raise _invalid("/amount", "INVALID", "Enter the amount found (+) or missing (-).")
        _check_amount(abs(amount), session.store.currency, "/amount")
    else:
        _check_amount(amount, session.store.currency, "/amount")
    if not reason.strip():
        raise _invalid("/reason", "REQUIRED", "Say what the cash was for.")
    with transaction.atomic():
        existing = (
            CashMovement.objects.for_org(ctx.organization)
            .filter(client_txn_id=client_txn_id)
            .first()
        )
        if existing is not None:
            return existing
        session = (
            CashSession.objects.for_org(ctx.organization).select_for_update().get(pk=session.pk)
        )
        if kind == CashMovement.Type.CORRECTION and session.status != CashSession.Status.CLOSED:
            raise CashRuleViolation("Corrections are for closed sessions. Count the till instead.")
        if kind != CashMovement.Type.CORRECTION and session.status != CashSession.Status.OPEN:
            raise CashRuleViolation("This till session is closed.")
        if kind in (CashMovement.Type.PAY_OUT, CashMovement.Type.DROP):
            in_drawer = expected_cash(session)
            if amount > in_drawer:
                raise CashRuleViolation(
                    f"Only {_money(in_drawer, session.store.currency)} should be in the drawer.",
                    code="NOT_ENOUGH_CASH",
                )
        movement = CashMovement.objects.create(
            organization=ctx.organization,
            session=session,
            movement_type=kind,
            amount=amount,
            reason=reason.strip(),
            client_txn_id=client_txn_id,
            created_by=ctx.user,
            occurred_at=timezone.now(),
        )
        record_audit(
            ctx.audit_actor,
            action=f"cash_session.{kind.value.lower()}",
            entity_type="cash_session",
            entity_id=session.pk,
            store_id=session.store_id,
            reason=reason.strip(),
            changes={"amount": [None, str(amount)]},
        )
    return movement


# --- Totals -------------------------------------------------------------------------------------


def _cash_payments(session: CashSession) -> Any:
    return Payment.objects.for_org(session.organization_id).filter(
        cash_session=session,
        payment_method__kind=PaymentMethod.Kind.CASH,
        status=Payment.Status.CONFIRMED,
    )


def _sum(queryset: Any, field: str = "amount") -> Decimal:
    return Decimal(queryset.aggregate(total=Sum(field))["total"] or 0)


def expected_cash(session: CashSession) -> Decimal:
    payments = _cash_payments(session)
    movements = CashMovement.objects.for_org(session.organization_id).filter(session=session)
    return (
        Decimal(session.opening_float)
        + _sum(payments.filter(direction=Payment.Direction.IN))
        - _sum(payments.filter(direction=Payment.Direction.OUT))
        + _sum(movements.filter(movement_type=CashMovement.Type.PAY_IN))
        - _sum(movements.filter(movement_type=CashMovement.Type.PAY_OUT))
        - _sum(movements.filter(movement_type=CashMovement.Type.DROP))
    )


def report(session: CashSession) -> dict[str, Any]:
    """The X report (open) or Z report (closed): everything that happened at the till."""
    from apps.sales.models import Sale, SaleReturn  # sales builds on cash

    org = session.organization_id
    payments = Payment.objects.for_org(org).filter(
        cash_session=session, status=Payment.Status.CONFIRMED
    )
    cash = payments.filter(payment_method__kind=PaymentMethod.Kind.CASH)
    movements = CashMovement.objects.for_org(org).filter(session=session)
    sales = Sale.objects.for_org(org).filter(cash_session=session)
    completed = sales.filter(status=Sale.Status.COMPLETED)
    voided = sales.filter(status=Sale.Status.VOIDED)
    returns = SaleReturn.objects.for_org(org).filter(cash_session=session)
    by_method = (
        payments.filter(direction=Payment.Direction.IN, purpose=Payment.Purpose.SALE)
        .values("payment_method__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("payment_method__position")
    )
    corrections = _sum(movements.filter(movement_type=CashMovement.Type.CORRECTION))
    expected = (
        session.expected_cash if session.expected_cash is not None else expected_cash(session)
    )
    return {
        "opening_float": session.opening_float,
        "sales_count": completed.count(),
        "sales_total": _sum(completed, "total"),
        "on_credit": _sum(completed, "amount_on_credit"),
        "voids_count": voided.count(),
        "voids_total": _sum(voided, "total"),
        "returns_count": returns.count(),
        "returns_total": _sum(returns, "total"),
        "by_method": [
            {"method": row["payment_method__name"], "count": row["count"], "total": row["total"]}
            for row in by_method
        ],
        "cash_in": _sum(cash.filter(direction=Payment.Direction.IN)),
        "cash_out": _sum(cash.filter(direction=Payment.Direction.OUT)),
        "pay_ins": _sum(movements.filter(movement_type=CashMovement.Type.PAY_IN)),
        "pay_outs": _sum(movements.filter(movement_type=CashMovement.Type.PAY_OUT)),
        "drops": _sum(movements.filter(movement_type=CashMovement.Type.DROP)),
        "expected_cash": expected,
        "counted_cash": session.counted_cash,
        "variance": session.variance,
        "corrections": corrections,
        "variance_after_corrections": (session.variance + corrections)
        if session.variance is not None
        else None,
    }


# --- Closing --------------------------------------------------------------------------------------


def close_session(
    ctx: RequestContext,
    session: CashSession,
    *,
    counted_cash: Decimal,
    denomination_count: dict[str, int] | None = None,
    variance_reason: str = "",
    at: datetime | None = None,
) -> CashSession:
    """The blind close-out: the count is entered before the expected amount is shown."""
    currency = session.store.currency
    _check_amount(counted_cash, currency, "/counted_cash", allow_zero=True)
    if denomination_count:
        counted = sum(
            (Decimal(value) * count for value, count in denomination_count.items()), Decimal(0)
        )
        if counted != counted_cash:
            raise _invalid(
                "/denomination_count",
                "DOES_NOT_ADD_UP",
                f"The notes and coins add up to {_money(counted, currency)}, "
                f"not {_money(counted_cash, currency)}.",
            )
    with transaction.atomic():
        session = (
            CashSession.objects.for_org(ctx.organization)
            .select_for_update()
            .select_related("store", "till")
            .get(pk=session.pk)
        )
        if session.status != CashSession.Status.OPEN:
            raise CashRuleViolation("This till session is already closed.")
        if session.opened_by_id != ctx.user.pk:
            require_permission(ctx, "cash.view_sessions")  # a manager closing someone's till
        expected = expected_cash(session)
        variance = counted_cash - expected
        over = abs(variance) > session.store.cash_variance_threshold
        if over and not variance_reason.strip():
            raise CashRuleViolation(
                "The count is out by more than the store allows. Say why before closing.",
                code="VARIANCE_REASON_REQUIRED",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=[{"pointer": "/variance_reason", "code": "REQUIRED"}],
            )
        session.status = CashSession.Status.CLOSED
        session.closed_by = ctx.user
        session.closed_at = at or timezone.now()
        session.expected_cash = expected
        session.counted_cash = counted_cash
        session.variance = variance
        session.variance_reason = variance_reason.strip()
        session.denomination_count = denomination_count or None
        session.save()
        record_audit(
            ctx.audit_actor,
            action="cash_session.closed",
            entity_type="cash_session",
            entity_id=session.pk,
            store_id=session.store_id,
            reason=session.variance_reason,
            changes={
                "expected_cash": [None, str(expected)],
                "counted_cash": [None, str(counted_cash)],
                "variance": [None, str(variance)],
            },
        )
        if over:
            # Picked up by the variance alerts (docs/ROADMAP.md 3.7).
            record_audit(
                ctx.audit_actor,
                action="cash_session.variance_alert",
                entity_type="cash_session",
                entity_id=session.pk,
                store_id=session.store_id,
                reason=session.variance_reason,
                changes={"variance": [None, str(variance)]},
            )
    return session
