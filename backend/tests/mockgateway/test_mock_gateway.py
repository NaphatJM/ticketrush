from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from mockgateway import services
from mockgateway import signing
from mockgateway.exceptions import ChargeExpired
from mockgateway.exceptions import ChargeNotPending
from mockgateway.exceptions import GatewayError
from mockgateway.exceptions import GatewayTimeoutError
from mockgateway.models import FaultConfig
from mockgateway.models import MockCharge
from mockgateway.tasks import deliver_webhook


pytestmark = pytest.mark.django_db

SECRET = 'test-secret'


def _charge(key='payment-1', amount=1000, expires_in=timedelta(minutes=5)):
    return services.create_charge(idempotency_key=key, amount_satang=amount, expires_at=timezone.now() + expires_in, timeout=5)


def _faults(**fields):
    FaultConfig.objects.update_or_create(pk=1, defaults=fields)


def test_a_signature_verifies_against_the_same_body():
    body = b'{"id":"evt_1"}'

    signing.verify(body, signing.sign(body, secret=SECRET), secret=SECRET)


@pytest.mark.parametrize(
    'header',
    [None, 'garbage', 't=1,v1=00', signing.sign(b'{"id":"evt_2"}', secret=SECRET), signing.sign(b'{"id":"evt_1"}', secret='other')],
    ids=['missing', 'malformed', 'wrong-digest', 'other-body', 'other-secret'],
)
def test_a_signature_that_does_not_match_is_rejected(header):
    with pytest.raises(signing.InvalidSignatureError):
        signing.verify(b'{"id":"evt_1"}', header, secret=SECRET)


def test_a_signature_outside_the_tolerance_is_rejected_as_a_replay():
    body = b'{}'
    header = signing.sign(body, secret=SECRET, timestamp=1_000)

    with pytest.raises(signing.InvalidSignatureError):
        signing.verify(body, header, secret=SECRET, now=1_000 + signing.TOLERANCE_SECONDS + 1)


def test_one_idempotency_key_creates_one_charge():
    first = _charge()
    second = _charge()

    assert first.charge_id == second.charge_id
    assert MockCharge.objects.count() == 1


def test_reusing_a_key_for_a_different_amount_is_refused():
    _charge(amount=1000)

    with pytest.raises(GatewayError):
        _charge(amount=2000)


def test_latency_above_the_timeout_is_a_timeout():
    _faults(latency_ms=10_000)

    with mock.patch('mockgateway.services.time.sleep') as sleep, pytest.raises(GatewayTimeoutError):
        _charge()

    sleep.assert_called_once_with(5)
    assert not MockCharge.objects.exists()


def test_the_error_rate_fails_charges():
    _faults(error_rate=1.0)

    with pytest.raises(GatewayError):
        _charge()


def test_paying_a_charge_sends_a_succeeded_webhook(django_capture_on_commit_callbacks):
    charge = _charge()

    with mock.patch('mockgateway.tasks.post_event') as post, django_capture_on_commit_callbacks(execute=True):
        services.pay(charge_id=charge.charge_id, succeed=True)

    event = post.call_args.args[0]
    assert event['type'] == 'charge.succeeded'
    assert event['data'] == {'charge_id': charge.charge_id, 'idempotency_key': 'payment-1', 'amount_satang': 1000, 'status': 'succeeded'}


def test_a_charge_is_settled_only_once():
    charge = _charge()
    services.pay(charge_id=charge.charge_id, succeed=False)

    with pytest.raises(ChargeNotPending):
        services.pay(charge_id=charge.charge_id, succeed=True)


def test_paying_after_the_expiry_fails_the_charge(django_capture_on_commit_callbacks):
    charge = _charge(expires_in=-timedelta(seconds=1))

    with mock.patch('mockgateway.tasks.post_event') as post, django_capture_on_commit_callbacks(execute=True), pytest.raises(ChargeExpired):
        services.pay(charge_id=charge.charge_id, succeed=True)

    assert post.call_args.args[0]['type'] == 'charge.failed'
    assert MockCharge.objects.get().status == MockCharge.Status.EXPIRED


@pytest.mark.parametrize(('faults', 'copies'), [({}, 1), ({'duplicate_webhook_rate': 1.0}, 2), ({'drop_webhook_rate': 1.0}, 0)])
def test_webhook_faults_duplicate_or_drop_deliveries(faults, copies):
    _faults(**faults)

    with mock.patch('mockgateway.tasks.post_event') as post:
        assert deliver_webhook(event={'id': 'evt_1'}) == copies

    assert post.call_count == copies
