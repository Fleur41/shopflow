"""Catalog master-data endpoints (docs/API.md §4.3): categories, brands, units, tax rates.

Behaviour shared with other master data (filters, versioned PATCH, no
DELETE, tenant scoping) lives in ``apps.organizations.api.master_data``.
"""

import uuid
from typing import Any, ClassVar

from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.pagination import DefaultCursorPagination
from apps.organizations.api.master_data import (
    LIST_FILTERS,
    MasterDataDetailView,
    MasterDataListView,
    patch_schema,
)

from .. import services
from ..models import Brand, Category, TaxRate, UnitOfMeasure
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


class _ListView(MasterDataListView):
    required_permissions: ClassVar[dict[str, str]] = _LIST_PERMISSIONS


class _DetailView(MasterDataDetailView):
    required_permissions: ClassVar[dict[str, str]] = _DETAIL_PERMISSIONS


class _ByCode(DefaultCursorPagination):
    ordering = ("code", "id")


# --- Categories ----------------------------------------------------------------------


class CategoryListView(_ListView):
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
            *LIST_FILTERS,
            OpenApiParameter(
                "parent",
                OpenApiTypes.STR,
                description="Subcategories of this category ID, or `none` for top-level ones",
            ),
        ]
    )
    def get(self, request: Request) -> Response:
        return self.list(request)


@patch_schema
class CategoryDetailView(_DetailView):
    model = Category
    serializer_class = CategorySerializer
    update_serializer_class = CategoryUpdateSerializer

    def update_entry(self, entry: Any, version: int, changes: dict[str, Any]) -> Category:
        return services.update_category(self.ctx, entry, version=version, **changes)


# --- Brands -------------------------------------------------------------------------


class BrandListView(_ListView):
    model = Brand
    serializer_class = BrandSerializer


@patch_schema
class BrandDetailView(_DetailView):
    model = Brand
    serializer_class = BrandSerializer
    update_serializer_class = BrandUpdateSerializer


# --- Units of measure ------------------------------------------------------------------


class UnitListView(_ListView):
    model = UnitOfMeasure
    serializer_class = UnitSerializer
    search_fields = ("code", "name")
    pagination_class = _ByCode


@patch_schema
class UnitDetailView(_DetailView):
    model = UnitOfMeasure
    serializer_class = UnitSerializer
    update_serializer_class = UnitUpdateSerializer


# --- Tax rates ------------------------------------------------------------------------------


class TaxRateListView(_ListView):
    model = TaxRate
    serializer_class = TaxRateSerializer


@patch_schema
class TaxRateDetailView(_DetailView):
    model = TaxRate
    serializer_class = TaxRateSerializer
    update_serializer_class = TaxRateUpdateSerializer
