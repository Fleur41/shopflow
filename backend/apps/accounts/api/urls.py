from django.urls import path

from . import account_views, views

app_name = "auth"

urlpatterns = [
    path("csrf/", views.CsrfTokenView.as_view(), name="csrf"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("logout-all/", views.LogoutAllView.as_view(), name="logout-all"),
    path("sessions/", views.SessionListView.as_view(), name="sessions"),
    path("sessions/<uuid:session_id>/", views.SessionRevokeView.as_view(), name="session-revoke"),
    path(
        "email/verification/",
        account_views.EmailVerificationRequestView.as_view(),
        name="email-verification",
    ),
    path("email/verify/", account_views.EmailVerifyView.as_view(), name="email-verify"),
    path("password/reset/", account_views.PasswordResetView.as_view(), name="password-reset"),
    path(
        "password/reset/confirm/",
        account_views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("password/change/", account_views.PasswordChangeView.as_view(), name="password-change"),
    path("mfa/totp/setup/", account_views.TOTPSetupView.as_view(), name="mfa-setup"),
    path("mfa/totp/confirm/", account_views.TOTPConfirmView.as_view(), name="mfa-confirm"),
    path("mfa/totp/disable/", account_views.TOTPDisableView.as_view(), name="mfa-disable"),
    path("mfa/verify/", account_views.MFAVerifyView.as_view(), name="mfa-verify"),
]
