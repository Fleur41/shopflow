"""Gapless, human-readable document numbers per store: ``MAIN-2026-000184``."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction

from .context import RequestContext
from .models import DocumentSequence, Store


def next_number(ctx: RequestContext, store: Store, doc_type: str, when: datetime) -> str:
    """Issue the next number. Must run inside the transaction that uses it, so a
    rollback gives the number back."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("next_number must run inside a transaction")
    year = when.astimezone(ZoneInfo(store.timezone)).year
    DocumentSequence.unscoped.bulk_create(
        [
            DocumentSequence(
                organization=ctx.organization, store=store, doc_type=doc_type, year=year
            )
        ],
        ignore_conflicts=True,
    )
    sequence = (
        DocumentSequence.objects.for_org(ctx.organization)
        .select_for_update()
        .get(store=store, doc_type=doc_type, year=year)
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value", "updated_at"])
    return f"{store.code}-{year}-{sequence.last_value:06d}"
