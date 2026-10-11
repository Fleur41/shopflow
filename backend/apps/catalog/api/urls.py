from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="categories"),
    path("categories/<uuid:entry_id>/", views.CategoryDetailView.as_view(), name="category-detail"),
    path("brands/", views.BrandListView.as_view(), name="brands"),
    path("brands/<uuid:entry_id>/", views.BrandDetailView.as_view(), name="brand-detail"),
    path("units/", views.UnitListView.as_view(), name="units"),
    path("units/<uuid:entry_id>/", views.UnitDetailView.as_view(), name="unit-detail"),
    path("tax-rates/", views.TaxRateListView.as_view(), name="tax-rates"),
    path("tax-rates/<uuid:entry_id>/", views.TaxRateDetailView.as_view(), name="tax-rate-detail"),
]
