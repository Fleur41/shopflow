from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.idempotency.models import IdempotencyKey


class Command(BaseCommand):
    help = "Delete expired idempotency keys (scheduled daily from Phase 2.6)."

    def handle(self, *args: Any, **options: Any) -> None:
        deleted, _ = IdempotencyKey.objects.filter(expires_at__lte=timezone.now()).delete()
        self.stdout.write(f"Deleted {deleted} expired idempotency keys.")
