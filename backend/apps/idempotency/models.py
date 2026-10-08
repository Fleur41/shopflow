from typing import ClassVar

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.common.models import BaseModel


class IdempotencyKey(BaseModel):
    """A client-chosen key and the response its first request produced.

    Inserted in the same transaction as the business change, so the key exists
    if and only if the change committed (docs/ARCHITECTURE.md, ADR-09).
    """

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=255)
    endpoint = models.CharField(max_length=255, help_text='e.g. "POST stores/"')
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True, encoder=DjangoJSONEncoder)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="idempotency_key_unique_per_org"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.endpoint} {self.key}"
