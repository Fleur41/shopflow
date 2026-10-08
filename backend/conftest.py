import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters, lockouts and cached sessions must not leak between tests."""
    cache.clear()
    yield
    cache.clear()
