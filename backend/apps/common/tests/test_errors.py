import pytest
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APIClient

from apps.common.errors import PROBLEM_CONTENT_TYPE, flatten_validation_errors

pytestmark = pytest.mark.urls("apps.common.tests.urls")


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def test_validation_error_is_flattened_to_json_pointers(client):
    response = client.post("/validate/", {"items": [{"quantity": "-1"}]}, format="json")

    assert response.status_code == 400
    assert response["Content-Type"] == PROBLEM_CONTENT_TYPE
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["type"] == "urn:shopflow:error:validation-error"
    pointers = {error["pointer"]: error["code"] for error in body["errors"]}
    assert pointers == {"/note": "REQUIRED", "/items/0/quantity": "MIN_VALUE"}
    assert body["request_id"] == response["X-Request-ID"]


def test_application_error_keeps_code_detail_and_errors(client):
    response = client.post("/business-rule/", {}, format="json")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INSUFFICIENT_STOCK"
    assert body["title"] == "Not enough stock"
    assert "only has 2 units" in body["detail"]
    assert body["errors"] == [{"pointer": "/items/0/quantity", "code": "INSUFFICIENT_STOCK"}]


def test_throttled_sets_retry_after(client):
    response = client.get("/throttled/")

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert response["Retry-After"] == "12"


def test_endpoints_deny_anonymous_access_by_default(client):
    response = client.get("/protected/")

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"
    assert "secret" not in response.content.decode()


def test_malformed_json_is_reported_without_internals(client):
    response = client.post("/validate/", "{not json", content_type="application/json")

    assert response.status_code == 400
    assert response.json()["code"] == "MALFORMED_REQUEST"


def test_unknown_url_returns_problem_json(client):
    response = client.get("/does-not-exist/")

    assert response.status_code == 404
    assert response["Content-Type"] == PROBLEM_CONTENT_TYPE
    assert response.json()["code"] == "NOT_FOUND"


def test_unexpected_exception_returns_generic_500_without_stack_trace():
    client = APIClient(raise_request_exception=False)

    response = client.get("/crash/")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["request_id"]
    assert "boom" not in response.content.decode()
    assert "Traceback" not in response.content.decode()


def test_flatten_handles_non_field_errors_and_escapes_pointer_tokens():
    detail = {
        "non_field_errors": [ErrorDetail("Totals do not match.", code="invalid")],
        "a/b~c": [ErrorDetail("Bad.", code="invalid")],
    }

    assert flatten_validation_errors(detail) == [
        {"pointer": "", "code": "INVALID", "detail": "Totals do not match."},
        {"pointer": "/a~1b~0c", "code": "INVALID", "detail": "Bad."},
    ]


def test_anonymous_request_gets_401_with_challenge(client):
    response = client.get("/protected/")

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


def test_django_http404_becomes_not_found_without_leaking_message(client):
    response = client.get("/django-404/")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert "internal detail" not in response.content.decode()


def test_django_permission_denied_becomes_403(client):
    response = client.get("/django-403/")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_application_error_status_can_be_overridden(client):
    response = client.post("/conflict/", {}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "PRICE_CHANGED"
    assert "errors" not in response.json()


def test_unknown_api_exception_uses_its_default_code():
    from rest_framework import exceptions

    from apps.common.errors import exception_handler

    class Gone(exceptions.APIException):
        status_code = 410
        default_code = "gone"
        default_detail = "This resource is gone."

    response = exception_handler(Gone(), {})

    assert response is not None
    assert response.status_code == 410
    assert response.data["code"] == "GONE"
    assert response.data["request_id"] is None


def test_django_level_400_and_403_handlers_return_problem_json(rf):
    from apps.common.views import bad_request, permission_denied

    request = rf.get("/")

    assert bad_request(request, Exception()).status_code == 400
    forbidden = permission_denied(request, Exception())
    assert forbidden.status_code == 403
    assert b"PERMISSION_DENIED" in forbidden.content
