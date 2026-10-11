from django.urls import path

from . import views

app_name = "suppliers"

urlpatterns = [
    path("suppliers/", views.SupplierListView.as_view(), name="suppliers"),
    path("suppliers/<uuid:entry_id>/", views.SupplierDetailView.as_view(), name="supplier-detail"),
    path(
        "suppliers/<uuid:supplier_id>/contacts/",
        views.SupplierContactsView.as_view(),
        name="supplier-contacts",
    ),
    path(
        "suppliers/<uuid:supplier_id>/contacts/<uuid:contact_id>/",
        views.SupplierContactDetailView.as_view(),
        name="supplier-contact-detail",
    ),
    path(
        "suppliers/<uuid:supplier_id>/products/",
        views.SupplierProductsView.as_view(),
        name="supplier-products",
    ),
    path(
        "products/<uuid:product_id>/suppliers/",
        views.ProductSuppliersView.as_view(),
        name="product-suppliers",
    ),
    path(
        "product-suppliers/<uuid:link_id>/",
        views.ProductSupplierDetailView.as_view(),
        name="product-supplier-detail",
    ),
]
