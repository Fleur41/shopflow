import re
from datetime import timedelta

import pytest
import time_machine
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.organizations.models import Invitation, Membership
from apps.organizations.testing import PASSWORD, client_for, role

pytestmark = pytest.mark.django_db
INVITEE_PASSPHRASE = "joining-the-duka-2026"


def _invite(client, biz, capture, **overrides):
    body = {
        "email": "Wairimu@Example.com",
        "role_id": str(role(biz.organization, "CASHIER").pk),
        "store_ids": [str(biz.branch.pk)],
    } | overrides
    with capture(execute=True):
        return client.post("/api/v1/invitations/", body, format="json")


def _token(mailoutbox):
    match = re.search(r"accept-invite\?token=([A-Za-z0-9_-]+)", mailoutbox[-1].body)
    assert match
    return match.group(1)


def _accept(token, client=None, **body):
    return (client or APIClient()).post(
        "/api/v1/auth/invitations/accept/", {"token": token, "client": "mobile", **body}
    )


def test_inviting_emails_a_link_and_lists_the_invitation(
    owner_client, biz, mailoutbox, django_capture_on_commit_callbacks
):
    response = _invite(owner_client, biz, django_capture_on_commit_callbacks)

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    (message,) = mailoutbox
    assert message.to == ["wairimu@example.com"]
    assert "Duka A" in message.subject
    listed = owner_client.get("/api/v1/invitations/").json()["results"]
    assert [i["email"] for i in listed] == ["wairimu@example.com"]
    assert AuditLog.objects.filter(action="invitation.created").exists()


def test_new_people_create_their_account_when_accepting(
    owner_client, biz, mailoutbox, django_capture_on_commit_callbacks
):
    _invite(owner_client, biz, django_capture_on_commit_callbacks)
    token = _token(mailoutbox)

    preview = APIClient().post("/api/v1/auth/invitations/preview/", {"token": token}).json()
    weak = _accept(token, full_name="Wairimu N", password="123")
    accepted = _accept(token, full_name="Wairimu N", password=INVITEE_PASSPHRASE)
    again = _accept(token, full_name="Wairimu N", password=INVITEE_PASSPHRASE)

    assert preview == {
        "organization_name": "Duka A", "email": "wairimu@example.com", "role_name": "Cashier",
        "account_exists": False, "expires_at": preview["expires_at"],
    }  # fmt: skip
    assert weak.status_code == 400
    assert accepted.status_code == 201
    assert accepted.json()["tokens"]["access_token"]
    user = User.objects.get(email="wairimu@example.com")
    assert user.email_verified_at is not None  # they proved it by opening the email
    membership = Membership.objects.for_org(biz.organization).get(user=user)
    assert [s.code for s in membership.stores.all()] == ["BR2"]
    assert again.status_code == 400
    assert again.json()["code"] == "INVITATION_INVALID"


def test_existing_accounts_must_be_signed_in_as_the_invitee(
    owner_client, biz, other_biz, mailoutbox, django_capture_on_commit_callbacks
):
    invitee = other_biz.user  # already has a ShopFlow account
    _invite(owner_client, biz, django_capture_on_commit_callbacks, email=invitee.email)
    token = _token(mailoutbox)

    anonymous = _accept(token)
    someone_else = _accept(token, client=client_for(biz.cashier.user, biz.organization))
    as_invitee = _accept(token, client=client_for(invitee, other_biz.organization))

    assert anonymous.status_code == 403
    assert anonymous.json()["code"] == "SIGN_IN_REQUIRED"
    assert someone_else.status_code == 403
    assert as_invitee.status_code == 200
    assert as_invitee.json() == {"organization_id": str(biz.organization.pk)}
    invitee.refresh_from_db()
    assert invitee.check_password(PASSWORD)  # nobody else could change their credentials


def test_existing_member_cannot_be_invited(owner_client, biz, django_capture_on_commit_callbacks):
    response = _invite(
        owner_client, biz, django_capture_on_commit_callbacks, email=biz.cashier.user.email
    )

    assert response.status_code == 409


def test_a_new_invitation_replaces_the_pending_one(
    owner_client, biz, mailoutbox, django_capture_on_commit_callbacks
):
    _invite(owner_client, biz, django_capture_on_commit_callbacks)
    first = _token(mailoutbox)
    _invite(owner_client, biz, django_capture_on_commit_callbacks)

    assert _accept(first, full_name="W", password=INVITEE_PASSPHRASE).status_code == 400
    assert (
        _accept(_token(mailoutbox), full_name="W", password=INVITEE_PASSPHRASE).status_code == 201
    )


def test_revoked_and_expired_invitations_cannot_be_used(
    owner_client, biz, mailoutbox, django_capture_on_commit_callbacks
):
    invitation_id = _invite(owner_client, biz, django_capture_on_commit_callbacks).json()["id"]
    revoked_token = _token(mailoutbox)
    owner_client.post(f"/api/v1/invitations/{invitation_id}/revoke/")
    _invite(owner_client, biz, django_capture_on_commit_callbacks, email="late@example.com")

    assert _accept(revoked_token, full_name="W", password=INVITEE_PASSPHRASE).status_code == 400
    with time_machine.travel(timezone.now() + timedelta(days=7, seconds=1)):
        expired = _accept(_token(mailoutbox), full_name="L", password=INVITEE_PASSPHRASE)
    assert expired.status_code == 400
    assert Invitation.objects.for_org(biz.organization).get(pk=invitation_id).status == "REVOKED"


def test_invitations_follow_the_same_privilege_rules(
    supervisor_client, biz, django_capture_on_commit_callbacks
):
    as_manager = _invite(
        supervisor_client, biz, django_capture_on_commit_callbacks,
        role_id=str(role(biz.organization, "MANAGER").pk), store_ids=[str(biz.store.pk)],
    )  # fmt: skip
    other_store = _invite(supervisor_client, biz, django_capture_on_commit_callbacks)

    assert as_manager.status_code == 403
    assert other_store.status_code == 403


def test_adding_an_existing_account_directly_points_to_invitations(owner_client, biz, other_biz):
    response = owner_client.post(
        "/api/v1/members/",
        {
            "email": other_biz.user.email, "full_name": "X", "password": INVITEE_PASSPHRASE,
            "role_id": str(role(biz.organization, "CASHIER").pk), "all_stores": True,
        },
        format="json",
    )  # fmt: skip

    assert response.status_code == 400
    assert "Invite them instead" in response.json()["errors"][0]["detail"]
