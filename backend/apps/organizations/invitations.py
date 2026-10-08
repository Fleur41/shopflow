"""Inviting people by email, including people who already have an account.

The invite is validated with the same privilege rules as adding a member
(you can only grant roles and stores within your own access). Accepting is
a separate step by the invitee; for an existing account it requires being
signed in as that account, so no business can attach itself to someone
else's account without their consent.
"""

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status

from apps.accounts.emails import link, send_templated_email
from apps.accounts.models import User, normalize_email_address
from apps.accounts.tokens import generate_refresh_token, hash_refresh_token
from apps.audit.services import AuditActor, record_audit
from apps.common.errors import ApplicationError

from .context import RequestContext
from .errors import AlreadyAMember
from .models import Invitation, Membership, MembershipStore, Role, Store
from .services import _require_assignable, _require_store_scope


class InvitationInvalid(ApplicationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVITATION_INVALID"
    title = "Invitation not valid"


class SignInRequired(ApplicationError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "SIGN_IN_REQUIRED"
    title = "Sign in to accept"


def invite_member(
    ctx: RequestContext, *, email: str, role: Role, all_stores: bool, stores: list[Store]
) -> Invitation:
    _require_assignable(ctx, role)
    _require_store_scope(ctx, all_stores, stores)
    normalized = normalize_email_address(email)
    if Membership.objects.for_org(ctx.organization).filter(user__email=normalized).exists():
        raise AlreadyAMember("This person is already a member of your business.")
    raw = generate_refresh_token()
    now = timezone.now()
    with transaction.atomic():
        # A new invitation replaces any pending one for the same address.
        Invitation.objects.for_org(ctx.organization).filter(
            email=normalized, accepted_at__isnull=True, revoked_at__isnull=True
        ).update(revoked_at=now)
        invitation = Invitation.objects.create(
            organization=ctx.organization,
            email=normalized,
            role=role,
            all_stores=all_stores,
            store_ids=[] if all_stores else sorted(str(s.pk) for s in stores),
            invited_by=ctx.user,
            token_hash=hash_refresh_token(raw),
            expires_at=now + settings.INVITATION_LIFETIME,
        )
        record_audit(
            ctx.audit_actor,
            action="invitation.created",
            entity_type="invitation",
            entity_id=invitation.pk,
            changes={
                "role": [None, role.name],
                "all_stores": [None, all_stores],
                "stores": [[], sorted(s.code for s in stores)],
            },
        )
        send_templated_email(
            to=normalized,
            template="invitation",
            context={
                "inviter": ctx.user.full_name,
                "organization": ctx.organization.name,
                "role": role.name,
                "url": link("/accept-invite", raw),
            },
        )
    return invitation


def revoke_invitation(ctx: RequestContext, invitation: Invitation) -> Invitation:
    with transaction.atomic():
        invitation = (
            Invitation.objects.for_org(ctx.organization).select_for_update().get(pk=invitation.pk)
        )
        if invitation.status == "PENDING":
            invitation.revoked_at = timezone.now()
            invitation.save(update_fields=["revoked_at", "updated_at"])
            record_audit(
                ctx.audit_actor,
                action="invitation.revoked",
                entity_type="invitation",
                entity_id=invitation.pk,
            )
    return invitation


@dataclass(frozen=True)
class InvitationPreview:
    organization_name: str
    email: str
    role_name: str
    account_exists: bool
    expires_at: object


def preview(raw: str) -> InvitationPreview:
    invitation = _pending(raw, lock=False)
    return InvitationPreview(
        organization_name=invitation.organization.name,
        email=invitation.email,
        role_name=invitation.role.name,
        account_exists=User.objects.filter(email=invitation.email).exists(),
        expires_at=invitation.expires_at,
    )


def accept_invitation(
    raw: str, *, signed_in_user: User | None, full_name: str = "", password: str | None = None
) -> Membership:
    """Join the business. New people create their account here (email is then verified)."""
    with transaction.atomic():
        invitation = _pending(raw, lock=True)
        existing = User.objects.filter(email=invitation.email).first()
        if existing is not None:
            if signed_in_user is None or signed_in_user.pk != existing.pk:
                raise SignInRequired(f"Sign in as {invitation.email} to accept this invitation.")
            user = existing
        else:
            if not full_name or not password:
                raise InvitationInvalid("Enter your name and choose a password to join.")
            try:
                validate_password(password, user=User(email=invitation.email, full_name=full_name))
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": list(exc.messages)}) from exc
            user = User.objects.create_user(
                invitation.email, password, full_name=full_name, email_verified_at=timezone.now()
            )
        if Membership.objects.for_org(invitation.organization).filter(user=user).exists():
            raise AlreadyAMember("You're already a member of this business.")

        membership = Membership.objects.create(
            organization=invitation.organization,
            user=user,
            role=invitation.role,
            all_stores=invitation.all_stores,
        )
        stores = list(
            Store.objects.for_org(invitation.organization).filter(pk__in=invitation.store_ids)
        )
        MembershipStore.objects.bulk_create(
            MembershipStore(membership=membership, store=store) for store in stores
        )
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = user
        invitation.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
        record_audit(
            AuditActor(organization_id=invitation.organization_id, user_id=user.pk),
            action="membership.added",
            entity_type="membership",
            entity_id=membership.pk,
            changes={
                "user": [None, str(user.pk)],
                "role": [None, invitation.role.name],
                "via_invitation": [None, str(invitation.pk)],
            },
        )
    return membership


def _pending(raw: str, *, lock: bool) -> Invitation:
    invitations = Invitation.unscoped.select_related("organization", "role")
    if lock:
        invitations = invitations.select_for_update(of=("self",))
    invitation: Invitation | None = invitations.filter(token_hash=hash_refresh_token(raw)).first()
    if invitation is None or invitation.status != "PENDING":
        raise InvitationInvalid("This invitation is invalid, expired or was withdrawn.")
    return invitation
