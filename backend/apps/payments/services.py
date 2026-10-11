"""Payment method use cases. Generic create/update and auditing live in ``master_data``."""

from typing import Any

from django.db.models import Max

from apps.audit.services import AuditActor, record_audit
from apps.organizations import master_data
from apps.organizations.context import RequestContext
from apps.organizations.models import Organization

from .models import DEFAULT_ETIMS_TYPES, PaymentMethod

Kind = PaymentMethod.Kind

# Every new business starts with these; owners can rename, reorder or deactivate them.
DEFAULT_METHODS: list[dict[str, Any]] = [
    {"code": "CASH", "name": "Cash", "kind": Kind.CASH},
    # Q-22: M-Pesa is recorded with the transaction code the customer receives.
    {"code": "MPESA", "name": "M-Pesa", "kind": Kind.MOBILE_MONEY, "requires_reference": True},
    {"code": "CARD", "name": "Card", "kind": Kind.CARD},
]


def create_payment_method(ctx: RequestContext, **fields: Any) -> PaymentMethod:
    """Fill in the eTIMS payment type from the kind, and put new methods last."""
    fields.setdefault("etims_payment_type", DEFAULT_ETIMS_TYPES[fields["kind"]])
    if "position" not in fields:
        last = PaymentMethod.objects.for_org(ctx.organization).aggregate(last=Max("position"))
        fields["position"] = (last["last"] or 0) + 1
    return master_data.create_entry(ctx, PaymentMethod, **fields)


def create_default_payment_methods(organization: Organization, actor: AuditActor) -> None:
    """Called by sign-up, inside its transaction."""
    for position, fields in enumerate(DEFAULT_METHODS, start=1):
        method = PaymentMethod.objects.create(
            organization=organization,
            position=position,
            etims_payment_type=DEFAULT_ETIMS_TYPES[fields["kind"]],
            **fields,
        )
        record_audit(
            actor,
            action="payment_method.created",
            entity_type=PaymentMethod.audit_name,
            entity_id=method.pk,
            changes={"code": [None, method.code], "name": [None, method.name]},
        )
