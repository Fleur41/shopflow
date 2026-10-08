"""Every API endpoint must state who may call it. New endpoints fail here until they do."""

from rest_framework.permissions import AllowAny, IsAuthenticated

from apps.organizations.api.permissions import TenantAPIView
from apps.organizations.catalog import ALL_CODES

from .routes import api_routes

# Reachable without signing in. Each entry must be justified.
PUBLIC = {
    "api/v1/auth/csrf/",  # issues the CSRF token needed before sign-in
    "api/v1/auth/login/",
    "api/v1/auth/refresh/",  # authenticated by the refresh token itself
    "api/v1/auth/signup/",
    "api/v1/auth/email/verify/",  # the emailed single-use token is the credential
    "api/v1/auth/password/reset/",  # always 202; reveals nothing
    "api/v1/auth/password/reset/confirm/",  # emailed single-use token
    "api/v1/auth/mfa/verify/",  # authenticated by the short-lived MFA challenge token
    "api/v1/auth/invitations/preview/",  # the invitation token is the credential
    # Optionally authenticated: existing accounts must be signed in as the invitee
    # (enforced in the service); new people create their account here.
    "api/v1/auth/invitations/accept/",
}

# Signed-in, but about the caller's own account rather than a business.
ACCOUNT_SCOPED = {
    "api/v1/auth/logout/",
    "api/v1/auth/logout-all/",
    "api/v1/auth/me/",
    "api/v1/auth/sessions/",
    "api/v1/auth/sessions/<uuid:session_id>/",
    "api/v1/auth/switch-organization/",
    "api/v1/auth/email/verification/",
    "api/v1/auth/password/change/",
    "api/v1/auth/mfa/totp/setup/",
    "api/v1/auth/mfa/totp/confirm/",
    "api/v1/auth/mfa/totp/disable/",
    "api/v1/schema/",
    "api/v1/docs/",
}


def test_every_tenant_endpoint_declares_a_known_permission_for_each_method():
    problems = []
    for route in api_routes():
        if not issubclass(route.view_class, TenantAPIView):
            continue
        declared = route.view_class.required_permissions
        for method in route.methods:
            code = declared.get(method)
            if code not in ALL_CODES:
                problems.append(f"{method} /{route.path}: {code!r}")
        for method in set(declared) - set(route.methods):
            problems.append(f"/{route.path} declares {method} but has no handler")

    assert not problems, "Fix permission declarations:\n" + "\n".join(problems)


def test_every_other_endpoint_is_explicitly_public_or_account_scoped():
    problems = []
    for route in api_routes():
        if issubclass(route.view_class, TenantAPIView):
            continue
        classes = list(route.view_class.permission_classes)
        if AllowAny in classes:
            if route.path not in PUBLIC:
                problems.append(f"/{route.path} is public but not in PUBLIC")
        elif route.path not in ACCOUNT_SCOPED:
            problems.append(f"/{route.path} is neither a TenantAPIView nor in ACCOUNT_SCOPED")
        elif not any(issubclass(c, IsAuthenticated) for c in classes):
            problems.append(f"/{route.path} must require authentication")

    assert not problems, "\n".join(problems)


def test_allowlists_have_no_stale_entries():
    paths = {route.path for route in api_routes()}

    assert (PUBLIC | ACCOUNT_SCOPED) - paths == set()
