import pytest
from django.core.cache import cache
from django_guid import clear_guid
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader


@pytest.fixture(autouse=True)
def _isolate_request_context():
    yield
    cache.clear()
    clear_guid()


@pytest.fixture(scope='session')
def metrics_reader():
    # The global meter provider can be set once per process; instruments created at import forward to it from then on.
    reader = InMemoryMetricReader()
    metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))
    return reader
