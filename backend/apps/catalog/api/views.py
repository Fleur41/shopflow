"""Catalog master-data endpoints (docs/API.md §4.3): categories, brands, units, tax rates.

Entries are looked up within the caller's organization, so another
business's IDs return 404. There is no DELETE: entries are deactivated by
PATCHing ``is_active``.
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
from apps.organizations.api.permissions import TenantAPIView

from .. import services
from ..models import Brand, CatalogEntry, Category, TaxRate, UnitOfMeasure
from .serializers import (
    BrandSerializer,
    BrandUpdateSerializer,
    CategorySerializer,
    CategoryUpdateSerializer,
    TaxRateSerializer,
    TaxRateUpdateSerializer,
    UnitSerializer,
    UnitUpdateSerializer,
)

_LIST_PERMISSIONS = {"GET": "products.view", "POST": "products.manage"}
_DETAIL_PERMISSIONS = {"GET": "products.view", "PATCH": "products.manage"}

_FILTERS = [
    OpenApiParameter("is_active", OpenApiTypes.BOOL, description="Only active, or only inactive"),
    OpenApiParameter("search", OpenApiTypes.STR, description="Part of the name (or unit code)"),
]


class _ByName(DefaultCursorPagination):
    ordering = ("name", "id")


class _ByCode(DefaultCursorPagination):
    ordering = ("code", "id")


def _bool_param(request: Request, name: str) -> bool | None:
    value = request.query_params.get(name)
    if value is None or value == "":
        return None
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise serializers.ValidationError({name: ["Use true or false."]})


class _EntryListView(mixins.ListModelMixin, TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = _LIST_PERMISSIONS
    model: ClassVar[type[CatalogEntry]]
    search_fields: ClassVar[tuple[str, ...]] = ("name",)
    pagination_class: type[DefaultCursorPagination] = _ByName

    def get_queryset(self) -> QuerySet[Any]:
        entries = self.model.objects.for_org(self.ctx.organization)
        is_active = _bool_param(self.request, "is_active")
        if is_active is not None:
            entries = entries.filter(is_active=is_active)
        if search := self.request.query_params.get("search", "").strip():
            matches = Q()
            for field in self.search_fields:
                matches |= Q(**{f"{field}__icontains": search})
            entries = entries.filter(matches)
        return entries

    @extend_schema(parameters=_FILTERS)
    def get(self, request: Request) -> Response:
        return self.list(request)

    @idempotent(required=False)
    def post(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = services.create_entry(self.ctx, self.model, **serializer.validated_data)
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED)


class _EntryDetailView(TenantAPIView):
    required_permissions: ClassVar[dict[str, str]] = _DETAIL_PERMISSIONS
    model: ClassVar[type[CatalogEntry]]
    update_serializer_class: ClassVar[type[serializers.ModelSerializer[Any]]]

    def get_entry(self, entry_id: uuid.UUID) -> Any:
        entry = self.model.objects.for_org(self.ctx.organization).filter(pk=entry_id).first()
        if entry is None:
            raise Http404
        return entry

    def get(self, request: Request, entry_id: uuid.UUID) -> Response:
        return Response(self.get_serializer(self.get_entry(entry_id)).data)

    def patch(self, request: Request, entry_id: uuid.UUID) -> Response:
        entry = self.get_entry(entry_id)
        serializer = self.update_serializer_class(
            entry, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        entry = services.update_entry(self.ctx, entry, version=changes.pop("version"), **changes)
        return Response(self.get_serializer(entry).data)


def _patch_schema[V: type[_EntryDetailView]](view: V) -> V:
    """Document PATCH with the update serializer (it requires ``version``).

    Each view gets its own wrapper: ``extend_schema`` annotates the function it
    decorates, so decorating the inherited method would leak across views.
    """

    def patch(self: _EntryDetailView, request: Request, entry_id: uuid.UUID) -> Response:
        return _EntryDetailView.patch(self, request, entry_id)

    view.patch = extend_schema(  # type: ignore[method-assign]
        request=view.update_serializer_class,
        responses=view.serializer_class,  # type: ignore[misc]  # a class attribute on every subclass
    )(patch)
    return view


# --- Categories ----------------------------------------------------------------------


class CategoryListView(_EntryListView):
    model = Category
    serializer_class = CategorySerializer

    def get_queryset(self) -> QuerySet[Any]:
        entries = super().get_queryset()
        parent = self.request.query_params.get("parent", "").strip()
        if parent == "none":
            entries = entries.filter(parent__isnull=True)
        elif parent:
            try:
                entries = entries.filter(parent_id=uuid.UUID(parent))
            except ValueError:
                raise serializers.ValidationError(
                    {"parent": ["Use a category ID, or none for top-level categories."]}
                ) from None
        return entries

    @extend_schema(
        parameters=[
            *_FILTERS,
            OpenApiParameter(
                "parent",
                OpenApiTypes.STR,
                description="Subcategories of this category ID, or `none` for top-level ones",
            ),
        ]
    )
    def get(self, request: Request) -> Response:
        return self.list(request)


@_patch_schema
class CategoryDetailView(_EntryDetailView):
    model = Category
    serializer_class = CategorySerializer
    update_serializer_class = CategoryUpdateSerializer


# --- Brands -------------------------------------------------------------------------


class BrandListView(_EntryListView):
    model = Brand
    serializer_class = BrandSerializer


@_patch_schema
class BrandDetailView(_EntryDetailView):
    model = Brand
    serializer_class = BrandSerializer
    update_serializer_class = BrandUpdateSerializer


# --- Units of measure ------------------------------------------------------------------


class UnitListView(_EntryListView):
    model = UnitOfMeasure
    serializer_class = UnitSerializer
    search_fields = ("code", "name")
    pagination_class = _ByCode


@_patch_schema
class UnitDetailView(_EntryDetailView):
    model = UnitOfMeasure
    serializer_class = UnitSerializer
    update_serializer_class = UnitUpdateSerializer


# --- Tax rates ------------------------------------------------------------------------------


class TaxRateListView(_EntryListView):
    model = TaxRate
    serializer_class = TaxRateSerializer


@_patch_schema
class TaxRateDetailView(_EntryDetailView):
    model = TaxRate
    serializer_class = TaxRateSerializer
    update_serializer_class = TaxRateUpdateSerializer
