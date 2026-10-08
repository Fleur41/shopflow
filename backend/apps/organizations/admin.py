from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import Membership, Organization, Permission, Role, Store


class ReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Platform staff can inspect tenant data, but changes must go through the
    application so they are validated and audited."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(Organization)
class OrganizationAdmin(ReadOnlyAdmin):
    list_display = ("name", "slug", "base_currency", "status", "created_at")
    search_fields = ("name", "slug")


@admin.register(Store)
class StoreAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "organization", "currency", "is_active")


@admin.register(Role)
class RoleAdmin(ReadOnlyAdmin):
    list_display = ("name", "organization", "template", "is_system")


@admin.register(Membership)
class MembershipAdmin(ReadOnlyAdmin):
    list_display = ("user", "organization", "role", "all_stores", "status")


@admin.register(Permission)
class PermissionAdmin(ReadOnlyAdmin):
    list_display = ("code", "category", "is_sensitive", "description")
