from django.urls import path

from . import views

S = "stores/<uuid:store_id>/"

urlpatterns = [
    path(f"{S}products/lookup/", views.LookupView.as_view(), name="product-lookup"),
    path(f"{S}inventory/", views.InventoryListView.as_view(), name="inventory-list"),
    path(f"{S}inventory/movements/", views.MovementListView.as_view(), name="inventory-movements"),
    path(
        f"{S}inventory/adjustments/",
        views.AdjustmentListView.as_view(),
        name="inventory-adjustments",
    ),
    path(
        f"{S}inventory/adjustments/<uuid:adjustment_id>/",
        views.AdjustmentDetailView.as_view(),
        name="inventory-adjustment-detail",
    ),
    path(
        f"{S}inventory/opening-balance/",
        views.OpeningBalanceView.as_view(),
        name="inventory-opening-balance",
    ),
    path(
        f"{S}inventory/<uuid:product_id>/",
        views.StockLevelDetailView.as_view(),
        name="inventory-detail",
    ),
]
