from django.urls import path

from . import views

app_name = "auth"

urlpatterns = [
    path("csrf/", views.CsrfTokenView.as_view(), name="csrf"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("logout-all/", views.LogoutAllView.as_view(), name="logout-all"),
    path("me/", views.MeView.as_view(), name="me"),
    path("sessions/", views.SessionListView.as_view(), name="sessions"),
    path("sessions/<uuid:session_id>/", views.SessionRevokeView.as_view(), name="session-revoke"),
]
