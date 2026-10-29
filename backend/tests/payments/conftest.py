import pytest

from payments.services import gateway_breaker


@pytest.fixture(autouse=True)
def _close_the_gateway_circuit():
    gateway_breaker.record_success()
    yield
    gateway_breaker.record_success()
