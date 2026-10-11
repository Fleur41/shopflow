from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("payment-methods/", views.PaymentMethodListView.as_view(), name="payment-methods"),
    path(
        "payment-methods/<uuid:entry_id>/",
        views.PaymentMethodDetailView.as_view(),
        name="payment-method-detail",
    ),
]
