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
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-v1:schema"), name="docs"),
]

urlpatterns = [
    path("healthz", common_views.healthz, name="healthz"),
    path("readyz", common_views.readyz, name="readyz"),
    path("api/v1/", include((api_v1_patterns, "api-v1"))),
    path(settings.ADMIN_URL, admin.site.urls),
]

handler400 = "apps.common.views.bad_request"
handler403 = "apps.common.views.permission_denied"
handler404 = "apps.common.views.not_found"
handler500 = "apps.common.views.server_error"
