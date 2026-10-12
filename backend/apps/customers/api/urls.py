from django.urls import path

from . import views

C = "customers/<uuid:customer_id>/"

urlpatterns = [
    path("customers/", views.CustomerListView.as_view(), name="customer-list"),
    path("customers/<uuid:entry_id>/", views.CustomerDetailView.as_view(), name="customer-detail"),
    path(f"{C}account/", views.AccountView.as_view(), name="customer-account"),
    path(
        f"{C}account/opening-balance/",
        views.OpeningBalanceView.as_view(),
        name="customer-opening-balance",
    ),
    path(f"{C}ledger/", views.LedgerView.as_view(), name="customer-ledger"),
    path(
        f"{C}ledger/<uuid:entry_id>/reverse/",
        views.ReverseEntryView.as_view(),
        name="customer-entry-reverse",
    ),
    path(f"{C}payments/", views.PaymentView.as_view(), name="customer-payments"),
]
