"""Real concurrency against PostgreSQL: two clients refresh with the same token."""

import threading

import pytest
from django.db import connection

from apps.accounts import services
from apps.accounts.models import AuthSession, RefreshToken, User

from .conftest import PASSWORD


@pytest.mark.django_db(transaction=True)
def test_simultaneous_refreshes_with_one_token_yield_exactly_one_new_token():
    User.objects.create_user("race@example.com", PASSWORD, full_name="Race")
    issued = services.login(
        email="race@example.com",
        password=PASSWORD,
        client_type=AuthSession.ClientType.MOBILE,
        ip_address=None,
        user_agent="",
    )
    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def attempt() -> None:
        try:
            barrier.wait()
            outcomes.append(
                services.refresh(
                    refresh_token=issued.refresh_token,
                    client_type=AuthSession.ClientType.MOBILE,
                )
            )
        except services.RefreshInProgress as exc:
            outcomes.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    successes = [o for o in outcomes if isinstance(o, services.IssuedTokens)]
    races = [o for o in outcomes if isinstance(o, services.RefreshInProgress)]
    assert (len(successes), len(races)) == (1, 1)
    assert RefreshToken.objects.count() == 2  # the original plus exactly one replacement
    assert AuthSession.objects.get().revoked_at is None
