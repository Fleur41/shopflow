from django.urls import path

from . import views

S = "stores/<uuid:store_id>/"

urlpatterns = [
    path(f"{S}sales/", views.SaleListView.as_view(), name="sale-list"),
    path(f"{S}sales/<uuid:sale_id>/", views.SaleDetailView.as_view(), name="sale-detail"),
    path(f"{S}sales/<uuid:sale_id>/receipt/", views.ReceiptView.as_view(), name="sale-receipt"),
]
