import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_openapi_schema_generates_without_warnings(tmp_path):
    """Generated clients rely on the schema (ADR-16); every endpoint must be described."""
    call_command(
        "spectacular", "--file", str(tmp_path / "schema.yaml"), "--validate", "--fail-on-warn"
    )
