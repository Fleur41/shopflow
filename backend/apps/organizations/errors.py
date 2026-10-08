from rest_framework import status

from apps.common.errors import ApplicationError


class TenantAccessError(ApplicationError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Access denied"


class OrganizationRequired(TenantAccessError):
    code = "ORGANIZATION_REQUIRED"


class MembershipInactive(TenantAccessError):
    code = "MEMBERSHIP_INACTIVE"


class OrganizationSuspended(TenantAccessError):
    code = "ORGANIZATION_SUSPENDED"


class NotAMember(TenantAccessError):
    code = "NOT_A_MEMBER"


class MissingPermission(TenantAccessError):
    code = "PERMISSION_DENIED"


class MFAEnrollmentRequired(TenantAccessError):
    code = "MFA_ENROLLMENT_REQUIRED"
    title = "Two-step verification required"


class PrivilegeEscalation(TenantAccessError):
    code = "PRIVILEGE_ESCALATION"


class CannotModifySelf(TenantAccessError):
    code = "CANNOT_MODIFY_SELF"


class LastOwner(ApplicationError):
    code = "LAST_OWNER"
    title = "The business needs an owner"


class SystemRoleImmutable(ApplicationError):
    code = "SYSTEM_ROLE_IMMUTABLE"
    title = "This role cannot be changed"


class AlreadyAMember(ApplicationError):
    status_code = status.HTTP_409_CONFLICT
    code = "ALREADY_A_MEMBER"
    title = "Already a member"
