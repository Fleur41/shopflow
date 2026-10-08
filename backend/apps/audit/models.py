from typing import Any, ClassVar

from django.conf import settings
from django.db import models

from apps.common.ids import uuid7


class AppendOnlyError(RuntimeError):
    pass


class AuditLog(models.Model):
    """Who did what, to which record, when, and why. Append-only.

    Rows are written in the same transaction as the change they describe, so
    an audited change cannot commit without its audit record. A database
    trigger rejects UPDATE and DELETE; the model refuses them earlier with a
    clearer error (docs/SECURITY.md §10).
    """

    # The runtime database role gets no UPDATE/DELETE here (apps.common.db_grants).
    append_only = True

    class ActorType(models.TextChoices):
        USER = "USER", "User"
        SYSTEM = "SYSTEM", "System"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="+"
    )
    store = models.ForeignKey(
        "organizations.Store", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    actor_type = models.CharField(max_length=10, choices=ActorType.choices, default=ActorType.USER)
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    changes = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["organization", "entity_type", "entity_id"], name="audit_entity_idx"
            ),
            models.Index(fields=["organization", "occurred_at"], name="audit_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type}:{self.entity_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Audit log entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise AppendOnlyError("Audit log entries cannot be deleted.")
