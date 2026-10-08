"""Account emails. Sent after the transaction commits; failures are logged,
never raised, so a mail outage cannot undo or break the user's action."""

from collections.abc import Mapping
from typing import Any

import structlog
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string

logger = structlog.get_logger(__name__)


def send_templated_email(*, to: str, template: str, context: Mapping[str, Any]) -> None:
    def _send() -> None:
        subject = render_to_string(f"emails/{template}_subject.txt", context).strip()
        body = render_to_string(f"emails/{template}.txt", context)
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        except Exception:
            logger.exception("email.send_failed", template=template)

    transaction.on_commit(_send)


def link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_URL}{path}?token={token}"
