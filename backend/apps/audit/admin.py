from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only: nobody, including platform staff, edits audit history."""

    list_display = ("occurred_at", "action", "entity_type", "entity_id", "actor", "organization")
    list_filter = ("action", "entity_type")
    search_fields = ("entity_id", "request_id")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
