"""Parsing query-string filters into typed values with field-level errors."""

import uuid
from datetime import datetime

from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.request import Request


def uuid_param(request: Request, name: str) -> uuid.UUID | None:
    value = request.query_params.get(name, "")
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise serializers.ValidationError({name: ["Enter a valid ID."]}) from exc


def datetime_param(request: Request, name: str) -> datetime | None:
    value = request.query_params.get(name, "")
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise serializers.ValidationError({name: ["Enter a date and time (ISO 8601)."]})
    return parsed
