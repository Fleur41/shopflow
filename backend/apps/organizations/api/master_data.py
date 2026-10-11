"""Reusable API pieces for master data (``apps.organizations.master_data``).

List views support ``is_active`` and ``search`` filters; detail views support
GET and a versioned PATCH. There is no DELETE: entries are deactivated by
PATCHing ``is_active``. Lookups are scoped to the caller's organization, so
another business's IDs return 404. Subclasses declare ``required_permissions``.
"""

import uuid
from typing import Any, ClassVar

from django.db.models import Q, QuerySet
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.pagination import DefaultCursorPagination
from apps.idempotency.service import idempotent

from ..master_data import MasterData, create_entry, update_entry
from .permissions import TenantAPIView
from .serializers import _ctx

ENTRY_FIELDS = ("is_active", "version", "created_at", "updated_at")
READ_ONLY_FIELDS = ("id", "version", "created_at", "updated_at")

LIST_FILTERS = [
    OpenApiParameter("is_active", OpenApiTypes.BOOL, description="Only active, or only inactive"),
    OpenApiParameter("search", OpenApiTypes.STR, description="Part of the name (or code)"),
]


# --- Serializers ------------------------------------------------------------------------


# Rejects a value of a ``unique_fields`` field that another entry in the same
# scope already uses, ignoring case, so "Soda" and "soda" can't both exist.
# (A comment, not a docstring: drf-spectacular would publish a docstring as
# the description of every subclass's schema.)
class MasterDataSerializer[E: MasterData](serializers.ModelSerializer[E]):
    unique_fields: ClassVar[tuple[str, ...]] = ("name",)
    taken_messages: ClassVar[dict[str, str]] = {}

    def unique_scope(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return {}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        model: type[MasterData] = self.Meta.model
        entries = model.objects.for_org(_ctx(self).organization).filter(**self.unique_scope(attrs))
        if self.instance is not None:
            entries = entries.exclude(pk=self.instance.pk)
        errors: dict[str, list[str]] = {}
        for field in self.unique_fields:
            value = attrs.get(field, getattr(self.instance, field, None))
            if value in (None, ""):
                continue  # required-ness is the field's job; blank may mean "generate one"
            if entries.filter(**{f"{field}__iexact": value}).exists():
                errors[field] = [self.taken_messages.get(field, "This is already in use.")]
        if errors:
            raise serializers.ValidationError(errors, code="taken")
        return attrs


class VersionedUpdateMixin(serializers.Serializer[Any]):
    version = serializers.IntegerField(
        help_text="The version you last read; the update is refused if someone changed it since."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Updates are partial, which makes DRF skip required checks.
        if "version" not in attrs:
            raise serializers.ValidationError(
                {"version": ["This field is required."]}, code="required"
            )
        validated: dict[str, Any] = super().validate(attrs)
        return validated


# --- Views ------------------------------------------------------------------------------


class ByName(DefaultCursorPagination):
    ordering = ("name", "id")


def bool_param(request: Request, name: str) -> bool | None:
    value = request.query_params.get(name)
    if value is None or value == "":
        return None
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise serializers.ValidationError({name: ["Use true or false."]})


class MasterDataListView(mixins.ListModelMixin, TenantAPIView):
    model: ClassVar[type[MasterData]]
    search_fields: ClassVar[tuple[str, ...]] = ("name",)
    pagination_class: type[DefaultCursorPagination] = ByName

    def get_queryset(self) -> QuerySet[Any]:
        entries = self.model.objects.for_org(self.ctx.organization)
        is_active = bool_param(self.request, "is_active")
        if is_active is not None:
            entries = entries.filter(is_active=is_active)
        if search := self.request.query_params.get("search", "").strip():
            entries = self.filter_search(entries, search)
        return entries

    def filter_search(self, entries: QuerySet[Any], search: str) -> QuerySet[Any]:
        matches = Q()
        for field in self.search_fields:
            matches |= Q(**{f"{field}__icontains": search})
        return entries.filter(matches)

    def create_entry(self, fields: dict[str, Any]) -> MasterData:
        return create_entry(self.ctx, self.model, **fields)

    @extend_schema(parameters=LIST_FILTERS)
    def get(self, request: Request) -> Response:
        return self.list(request)

    @idempotent(required=False)
    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = self.create_entry(dict(serializer.validated_data))
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED)


class MasterDataDetailView(TenantAPIView):
    model: ClassVar[type[MasterData]]
    update_serializer_class: ClassVar[type[serializers.ModelSerializer[Any]]]

    def get_entry(self, entry_id: uuid.UUID) -> Any:
        entry = self.model.objects.for_org(self.ctx.organization).filter(pk=entry_id).first()
        if entry is None:
            raise Http404
        return entry

    def update_entry(self, entry: MasterData, version: int, changes: dict[str, Any]) -> MasterData:
        return update_entry(self.ctx, entry, version=version, **changes)

    def get(self, request: Request, entry_id: uuid.UUID) -> Response:
        return Response(self.get_serializer(self.get_entry(entry_id)).data)

    def patch(self, request: Request, entry_id: uuid.UUID) -> Response:
        entry = self.get_entry(entry_id)
        serializer = self.update_serializer_class(
            entry, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        entry = self.update_entry(entry, changes.pop("version"), changes)
        return Response(self.get_serializer(entry).data)


def patch_schema[V: type[MasterDataDetailView]](view: V) -> V:
    """Document PATCH with the update serializer (it requires ``version``).

    Each view gets its own wrapper: ``extend_schema`` annotates the function it
    decorates, so decorating the inherited method would leak across views.
    """

    def patch(self: MasterDataDetailView, request: Request, entry_id: uuid.UUID) -> Response:
        return MasterDataDetailView.patch(self, request, entry_id)

    view.patch = extend_schema(  # type: ignore[method-assign]
        request=view.update_serializer_class,
        responses=view.serializer_class,  # type: ignore[misc]  # a class attribute on every subclass
    )(patch)
    return view
