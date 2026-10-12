import pytest

from apps.sales.testing import build_shop


@pytest.fixture
def shop(db):
    return build_shop()
