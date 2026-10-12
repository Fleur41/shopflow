from django.conf import settings
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common import views as common_views
from apps.organizations.api import urls as tenancy_urls

api_v1_patterns: list[URLPattern | URLResolver] = [
    path("auth/", include("apps.accounts.api.urls")),
    path("auth/", include((tenancy_urls.auth_urlpatterns, "tenancy-auth"))),
    path("", include("apps.organizations.api.urls")),
    path("", include("apps.catalog.api.urls")),
    path("", include("apps.payments.api.urls")),
    path("", include("apps.suppliers.api.urls")),
    path("", include("apps.inventory.api.urls")),
    path("", include("apps.sales.api.urls")),
    path("", include("apps.customers.api.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-v1:schema"), name="docs"),
]

urlpatterns = [
    path("healthz", common_views.healthz, name="healthz"),
    path("readyz", common_views.readyz, name="readyz"),
    path("api/v1/", include((api_v1_patterns, "api-v1"))),
    path(settings.ADMIN_URL, admin.site.urls),
]

if settings.DEBUG:
    # Local development only: deployments serve uploads from object storage.
    urlpatterns.append(path("media/<path:path>", common_views.serve_media, name="media"))

handler400 = "apps.common.views.bad_request"
handler403 = "apps.common.views.permission_denied"
handler404 = "apps.common.views.not_found"
handler500 = "apps.common.views.server_error"
