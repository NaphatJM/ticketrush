import pytest
from django.core.cache import cache
from django_guid import clear_guid


@pytest.fixture(autouse=True)
def _isolate_request_context():
    yield
    cache.clear()
    clear_guid()
