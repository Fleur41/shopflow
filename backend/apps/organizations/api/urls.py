from django.urls import path

from . import views

app_name = "tenancy"

# Mounted under /api/v1/auth/ next to the accounts endpoints.
auth_urlpatterns = [
    path("signup/", views.SignupView.as_view(), name="signup"),
    path(
        "switch-organization/", views.SwitchOrganizationView.as_view(), name="switch-organization"
    ),
    path("me/", views.MeView.as_view(), name="me"),
]

urlpatterns = [
    path("organization/", views.OrganizationView.as_view(), name="organization"),
    path("stores/", views.StoreListView.as_view(), name="stores"),
    path("stores/<uuid:store_id>/", views.StoreDetailView.as_view(), name="store-detail"),
    path("permissions/", views.PermissionListView.as_view(), name="permissions"),
    path("roles/", views.RoleListView.as_view(), name="roles"),
    path("roles/<uuid:role_id>/", views.RoleDetailView.as_view(), name="role-detail"),
    path("members/", views.MemberListView.as_view(), name="members"),
    path("members/<uuid:member_id>/", views.MemberDetailView.as_view(), name="member-detail"),
    path(
        "members/<uuid:member_id>/suspend/",
        views.MemberSuspendView.as_view(),
        name="member-suspend",
    ),
    path(
        "members/<uuid:member_id>/reactivate/",
        views.MemberReactivateView.as_view(),
        name="member-reactivate",
    ),
]
