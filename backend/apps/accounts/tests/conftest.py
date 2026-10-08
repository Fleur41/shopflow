from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User

PASSWORD = "correct-horse-battery-staple"
LOGIN_URL = "/api/v1/auth/login/"


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user("cashier@example.com", PASSWORD, full_name="Jane Cashier")


@pytest.fixture
def make_web_client() -> Callable[[], APIClient]:
    """A browser-like client: enforces CSRF and carries the CSRF header."""

    def factory() -> APIClient:
        client = APIClient(enforce_csrf_checks=True)
        token = client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        client.credentials(HTTP_X_CSRFTOKEN=token)
        return client

    return factory


@pytest.fixture
def web_client(make_web_client) -> APIClient:
    return make_web_client()


@pytest.fixture
def signed_in_web_client(web_client, user) -> APIClient:
    response = web_client.post(LOGIN_URL, {"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.content
    return web_client


def mobile_login(client: APIClient, email: str, password: str = PASSWORD) -> dict:
    response = client.post(
        LOGIN_URL,
        {"email": email, "password": password, "client": "mobile", "device_name": "Till 2"},
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def mobile_session(user) -> tuple[APIClient, dict]:
    client = APIClient()
    body = mobile_login(client, user.email)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['tokens']['access_token']}")
    return client, body
