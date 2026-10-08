from typing import Any

import pytest

from apps.common.logging import REDACTED, redact, redact_sensitive


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "access_token",
        "Authorization",
        "csrftoken",
        "otp",
        "mfa_code",
        "pin",
        "api_key",
        "client_secret",
        "Cookie",
    ],
)
def test_sensitive_keys_are_redacted(key):
    assert redact({key: "value"}) == {key: REDACTED}


@pytest.mark.parametrize("key", ["shipping_address", "spinner", "product_name", "idempotency_key"])
def test_ordinary_keys_are_kept(key):
    assert redact({key: "value"}) == {key: "value"}


def test_redaction_is_recursive_and_does_not_mutate_input():
    event: dict[str, Any] = {
        "event": "login",
        "body": {"email": "a@b.co", "password": "hunter22"},
        "items": [{"refresh_token": "abc"}],
    }

    result = redact_sensitive(None, "info", event)

    assert result == {
        "event": "login",
        "body": {"email": "a@b.co", "password": REDACTED},
        "items": [{"refresh_token": REDACTED}],
    }
    assert event["body"]["password"] == "hunter22"


def test_json_mode_renders_json_lines():
    import json
    import logging

    from apps.common.logging import build_logging_config

    config = build_logging_config(json_logs=True, level="INFO")
    try:
        formatter_spec: dict[str, Any] = dict(config["formatters"]["structured"])
        formatter = formatter_spec.pop("()")(**formatter_spec)
        record = logging.LogRecord("shopflow", logging.INFO, __file__, 1, "login", None, None)

        line = json.loads(formatter.format(record))

        assert line["event"] == "login"
        assert line["level"] == "info"
        assert "timestamp" in line
    finally:
        build_logging_config(json_logs=False, level="WARNING")
