"""Supplier endpoints (docs/API.md §4.8).

Suppliers are master data (filters, versioned PATCH, no DELETE: deactivate).
Contacts and product links are address-book style: they can be removed, and
every change is audited.
"""

import uuid
from typing import Any, ClassVar

from django.db.models import QuerySet
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.common.pagination import DefaultCursorPagination
from apps.organizations.api.master_data import (
    MasterDataDetailView,
    MasterDataListView,
    patch_schema,
)
from apps.organizations.api.permissions import TenantAPIView
from apps.organizations.master_data import MasterData

from .. import services
from ..models import ProductSupplier, Supplier, SupplierContact
from .serializers import (
    LinkFromProductSerializer,
    LinkFromSupplierSerializer,
    ProductSupplierSerializer,
    ProductSupplierUpdateSerializer,
    SupplierContactSerializer,
    SupplierSerializer,
    SupplierUpdateSerializer,
)

_VIEW = "suppliers.view"
_MANAGE = "suppliers.manage"


class SupplierListView(MasterDataListView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": _VIEW, "POST": _MANAGE}
    model = Supplier
    serializer_class = SupplierSerializer
    search_fields = ("name", "code", "phone", "kra_pin")

    def create_entry(self, fields: dict[str, Any]) -> MasterData:
        return services.create_supplier(self.ctx, **fields)


@patch_schema
class SupplierDetailView(MasterDataDetailView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": _VIEW, "PATCH": _MANAGE}
    model = Supplier
    serializer_class = SupplierSerializer
    update_serializer_class = SupplierUpdateSerializer


class _Scoped(TenantAPIView):
    def get_supplier(self, supplier_id: uuid.UUID) -> Supplier:
        supplier = Supplier.objects.for_org(self.ctx.organization).filter(pk=supplier_id).first()
        if supplier is None:
            raise Http404
        return supplier

    def get_product(self, product_id: uuid.UUID) -> Product:
        product = Product.objects.for_org(self.ctx.organization).filter(pk=product_id).first()
        if product is None:
            raise Http404
        return product

    def links(self) -> QuerySet[ProductSupplier]:
        return ProductSupplier.objects.for_org(self.ctx.organization).select_related(
            "product", "supplier"
        )


# --- Contacts -------------------------------------------------------------------------


class SupplierContactsView(_Scoped):
    """A supplier's contacts, primary first. There are only ever a few."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": _VIEW, "POST": _MANAGE}
    serializer_class = SupplierContactSerializer
    pagination_class = None

    @extend_schema(responses=SupplierContactSerializer(many=True))
    def get(self, request: Request, supplier_id: uuid.UUID) -> Response:
        contacts = SupplierContact.objects.for_org(self.ctx.organization).filter(
            supplier=self.get_supplier(supplier_id)
        )
        return Response(
            self.get_serializer(contacts.order_by("-is_primary", "name"), many=True).data
        )

    def post(self, request: Request, supplier_id: uuid.UUID) -> Response:
        supplier = self.get_supplier(supplier_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact = services.add_contact(self.ctx, supplier, **serializer.validated_data)
        return Response(self.get_serializer(contact).data, status=status.HTTP_201_CREATED)


class SupplierContactDetailView(_Scoped):
    required_permissions: ClassVar[dict[str, str]] = {"PATCH": _MANAGE, "DELETE": _MANAGE}
    serializer_class = SupplierContactSerializer

    def get_contact(self, supplier_id: uuid.UUID, contact_id: uuid.UUID) -> SupplierContact:
        contact = (
            SupplierContact.objects.for_org(self.ctx.organization)
            .filter(supplier=self.get_supplier(supplier_id), pk=contact_id)
            .first()
        )
        if contact is None:
            raise Http404
        return contact

    def patch(self, request: Request, supplier_id: uuid.UUID, contact_id: uuid.UUID) -> Response:
        contact = self.get_contact(supplier_id, contact_id)
        serializer = self.get_serializer(contact, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        contact = services.update_contact(self.ctx, contact, **serializer.validated_data)
        return Response(self.get_serializer(contact).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, supplier_id: uuid.UUID, contact_id: uuid.UUID) -> Response:
        services.remove_contact(self.ctx, self.get_contact(supplier_id, contact_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Product links ----------------------------------------------------------------------


class _ByProductName(DefaultCursorPagination):
    ordering = ("product__name", "id")


class SupplierProductsView(_Scoped):
    """The products a supplier supplies."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": _VIEW, "POST": _MANAGE}
    serializer_class = ProductSupplierSerializer
    pagination_class = _ByProductName

    @extend_schema(responses=ProductSupplierSerializer(many=True))
    def get(self, request: Request, supplier_id: uuid.UUID) -> Response:
        links = self.links().filter(supplier=self.get_supplier(supplier_id))
        page = self.paginate_queryset(links)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @extend_schema(request=LinkFromSupplierSerializer, responses={201: ProductSupplierSerializer})
    def post(self, request: Request, supplier_id: uuid.UUID) -> Response:
        supplier = self.get_supplier(supplier_id)
        serializer = LinkFromSupplierSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        link = services.link_product(self.ctx, supplier=supplier, **serializer.validated_data)
        return Response(self.get_serializer(link).data, status=status.HTTP_201_CREATED)


class ProductSuppliersView(_Scoped):
    """The suppliers of a product, preferred first. There are only ever a few."""

    required_permissions: ClassVar[dict[str, str]] = {"GET": _VIEW, "POST": _MANAGE}
    serializer_class = ProductSupplierSerializer
    pagination_class = None

    @extend_schema(responses=ProductSupplierSerializer(many=True))
    def get(self, request: Request, product_id: uuid.UUID) -> Response:
        links = self.links().filter(product=self.get_product(product_id))
        return Response(
            self.get_serializer(links.order_by("-is_preferred", "supplier__name"), many=True).data
        )

    @extend_schema(request=LinkFromProductSerializer, responses={201: ProductSupplierSerializer})
    def post(self, request: Request, product_id: uuid.UUID) -> Response:
        product = self.get_product(product_id)
        serializer = LinkFromProductSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        link = services.link_product(self.ctx, product=product, **serializer.validated_data)
        return Response(self.get_serializer(link).data, status=status.HTTP_201_CREATED)


class ProductSupplierDetailView(_Scoped):
    required_permissions: ClassVar[dict[str, str]] = {"PATCH": _MANAGE, "DELETE": _MANAGE}
    serializer_class = ProductSupplierUpdateSerializer

    def get_link(self, link_id: uuid.UUID) -> ProductSupplier:
        link = self.links().filter(pk=link_id).first()
        if link is None:
            raise Http404
        return link

    @extend_schema(responses=ProductSupplierSerializer)
    def patch(self, request: Request, link_id: uuid.UUID) -> Response:
        link = self.get_link(link_id)
        serializer = self.get_serializer(link, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        link = services.update_link(self.ctx, link, **serializer.validated_data)
        return Response(ProductSupplierSerializer(link, context=self.get_serializer_context()).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, link_id: uuid.UUID) -> Response:
        services.unlink_product(self.ctx, self.get_link(link_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
