"""Catalog master-data endpoints (docs/API.md §4.3): categories, brands, units, tax rates.

Behaviour shared with other master data (filters, versioned PATCH, no
DELETE, tenant scoping) lives in ``apps.organizations.api.master_data``.
"""

import uuid
from typing import Any, ClassVar

from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.pagination import DefaultCursorPagination
from apps.idempotency.service import idempotent
from apps.organizations.api.master_data import (
    LIST_FILTERS,
    MasterDataDetailView,
    MasterDataListView,
    patch_schema,
)
from apps.organizations.api.permissions import TenantAPIView
from apps.organizations.master_data import MasterData

from .. import images, products, services
from ..models import (
    Brand,
    Category,
    Product,
    ProductIdentifier,
    ProductPriceHistory,
    TaxRate,
    UnitOfMeasure,
)
from .serializers import (
    BrandSerializer,
    BrandUpdateSerializer,
    CategorySerializer,
    CategoryUpdateSerializer,
    PriceHistorySerializer,
    ProductIdentifierSerializer,
    ProductSerializer,
    ProductUpdateSerializer,
    TaxRateSerializer,
    TaxRateUpdateSerializer,
    UnitSerializer,
    UnitUpdateSerializer,
)

_LIST_PERMISSIONS = {"GET": "products.view", "POST": "products.manage"}
SEARCH_SIMILARITY = 0.4
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


# --- Products ---------------------------------------------------------------------------


class ProductListView(_ListView):
    model = Product
    serializer_class = ProductSerializer

    def get_queryset(self) -> QuerySet[Any]:
        products = (
            super()
            .get_queryset()
            .select_related("category", "brand", "unit", "tax_rate")
            .prefetch_related("identifiers")
        )
        params = self.request.query_params
        if sku := params.get("sku", "").strip():
            products = products.filter(sku__iexact=sku)
        if barcode := params.get("barcode", "").strip():
            products = products.filter(
                Exists(
                    ProductIdentifier.objects.for_org(self.ctx.organization).filter(
                        product=OuterRef("pk"), value=barcode
                    )
                )
            )
        for name in ("category", "brand"):
            if value := params.get(name, "").strip():
                products = products.filter(**{f"{name}_id": _uuid_param(name, value)})
        return products

    def filter_search(self, entries: QuerySet[Any], search: str) -> QuerySet[Any]:
        # Part of the name, a near miss ("suger" finds "Sugar"), or an exact code.
        # The default word-similarity threshold (0.6) misses one-letter typos in
        # short words; 0.4 catches them. Set for this transaction only (see get()),
        # so the index-backed ``%>`` operator still does the work.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('pg_trgm.word_similarity_threshold', %s, true)",
                [str(SEARCH_SIMILARITY)],
            )
        return entries.filter(
            Q(name__icontains=search)
            | Q(name__trigram_word_similar=search)
            | Q(sku__iexact=search)
            | Exists(
                ProductIdentifier.objects.for_org(self.ctx.organization).filter(
                    product=OuterRef("pk"), value=search
                )
            )
        )

    def create_entry(self, fields: dict[str, Any]) -> MasterData:
        return products.create_product(self.ctx, **fields)

    @extend_schema(
        parameters=[
            *LIST_FILTERS,
            OpenApiParameter("sku", OpenApiTypes.STR, description="Exact SKU, ignoring case"),
            OpenApiParameter(
                "barcode", OpenApiTypes.STR, description="Exact barcode or other code"
            ),
            OpenApiParameter("category", OpenApiTypes.UUID),
            OpenApiParameter("brand", OpenApiTypes.UUID),
        ]
    )
    def get(self, request: Request) -> Response:
        with transaction.atomic():  # scopes the similarity threshold to this request
            return self.list(request)


@patch_schema
class ProductDetailView(_DetailView):
    """PATCH changing ``selling_price`` also needs ``products.change_price``."""

    model = Product
    serializer_class = ProductSerializer
    update_serializer_class = ProductUpdateSerializer

    def update_entry(self, entry: Any, version: int, changes: dict[str, Any]) -> Product:
        return products.update_product(self.ctx, entry, version=version, **changes)


class _ProductChildView(TenantAPIView):
    def get_product(self, product_id: uuid.UUID) -> Product:
        product = Product.objects.for_org(self.ctx.organization).filter(pk=product_id).first()
        if product is None:
            raise Http404
        return product


class ProductIdentifiersView(_ProductChildView):
    required_permissions: ClassVar[dict[str, str]] = _LIST_PERMISSIONS
    serializer_class = ProductIdentifierSerializer

    @extend_schema(responses=ProductIdentifierSerializer(many=True))
    def get(self, request: Request, product_id: uuid.UUID) -> Response:
        identifiers = ProductIdentifier.objects.for_org(self.ctx.organization).filter(
            product=self.get_product(product_id)
        )
        return Response(self.get_serializer(identifiers.order_by("id"), many=True).data)

    @idempotent(required=False)
    def post(self, request: Request, product_id: uuid.UUID) -> Response:
        product = self.get_product(product_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = products.add_identifier(self.ctx, product, **serializer.validated_data)
        return Response(self.get_serializer(identifier).data, status=status.HTTP_201_CREATED)


class ProductIdentifierDetailView(_ProductChildView):
    required_permissions: ClassVar[dict[str, str]] = {"DELETE": "products.manage"}

    @extend_schema(responses={204: None})
    def delete(self, request: Request, product_id: uuid.UUID, identifier_id: uuid.UUID) -> Response:
        identifier = (
            ProductIdentifier.objects.for_org(self.ctx.organization)
            .filter(product=self.get_product(product_id), pk=identifier_id)
            .first()
        )
        if identifier is None:
            raise Http404
        products.remove_identifier(self.ctx, identifier)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductImageView(_ProductChildView):
    """Upload (multipart field ``image``) or remove a product's image."""

    required_permissions: ClassVar[dict[str, str]] = {
        "POST": "products.manage",
        "DELETE": "products.manage",
    }
    parser_classes = (MultiPartParser,)

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"image": {"type": "string", "format": "binary"}},
            }
        },
        responses=ProductSerializer,
    )
    def post(self, request: Request, product_id: uuid.UUID) -> Response:
        product = self.get_product(product_id)  # before reading the body: 404 first
        upload = request.FILES.get("image")
        if upload is None:
            raise serializers.ValidationError({"image": ["Choose an image file."]})
        try:
            product = products.set_image(self.ctx, product, upload)
        except images.InvalidImage as exc:
            raise serializers.ValidationError({"image": [str(exc)]}, code="invalid") from exc
        return Response(ProductSerializer(product, context=self.get_serializer_context()).data)

    @extend_schema(responses=ProductSerializer)
    def delete(self, request: Request, product_id: uuid.UUID) -> Response:
        product = products.remove_image(self.ctx, self.get_product(product_id))
        return Response(ProductSerializer(product, context=self.get_serializer_context()).data)


class _NewestFirst(DefaultCursorPagination):
    ordering = ("-changed_at", "-id")


class ProductPriceHistoryView(mixins.ListModelMixin, _ProductChildView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "products.view"}
    serializer_class = PriceHistorySerializer
    pagination_class = _NewestFirst

    def get_queryset(self) -> QuerySet[Any]:
        product = self.get_product(self.kwargs["product_id"])
        return ProductPriceHistory.objects.filter(
            organization=self.ctx.organization, product=product
        ).select_related("changed_by")

    def get(self, request: Request, product_id: uuid.UUID) -> Response:
        return self.list(request)


def _uuid_param(name: str, value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise serializers.ValidationError({name: ["Use an ID."]}) from None
