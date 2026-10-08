"""Structured logging.

Every log line is a structured event (JSON in deployed environments) that
carries the request context bound by :class:`RequestIDMiddleware`. A
redaction processor removes secrets before anything is rendered; see
docs/SECURITY.md §8 for what must never be logged.
"""

import re
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED = "[REDACTED]"

# Keys containing any of these substrings are always redacted.
_SENSITIVE_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "credential",
    "apikey",
    "api_key",
    "private_key",
)
# Keys whose individual words (split on _ - . or space) match exactly are redacted.
# Matching on words avoids false positives such as "shipping" containing "pin".
_SENSITIVE_WORDS = frozenset({"pin", "otp", "pwd", "cvv", "pan", "mfa"})
_WORD_SPLIT = re.compile(r"[_\-.\s]+")


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if any(fragment in lowered for fragment in _SENSITIVE_SUBSTRINGS):
        return True
    return any(word in _SENSITIVE_WORDS for word in _WORD_SPLIT.split(lowered))


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with sensitive mapping keys masked, recursively."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(redact(item) for item in value)
    return value


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """structlog processor applying :func:`redact` to every event."""
    return redact(event_dict)  # type: ignore[no-any-return]


def build_logging_config(*, json_logs: bool, level: str) -> dict[str, Any]:
    """Configure structlog and return a matching ``LOGGING`` dict for Django.

    Standard-library loggers (Django, gunicorn, libraries) are routed through
    the same processors, so all output shares one format.
    """
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    renderer: Processor
    if json_logs:
        renderer = structlog.processors.JSONRenderer()
        shared.append(structlog.processors.dict_tracebacks)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structured": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    renderer,
                ],
                "foreign_pre_chain": shared,
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "structured",
            }
        },
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            # Request logging is done by RequestIDMiddleware; avoid duplicates.
            "django.server": {"level": "WARNING"},
        },
    }
