from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from mockgateway.exceptions import GatewayError
from payments import services as payment_services
from payments.exceptions import PaymentsUnavailable
from payments.tasks import process_succeeded
from reliability.models import DeadLetter
from reliability.models import OutboxMessage
from tests.builders import make_event
from tests.builders import make_hold
from tests.builders import make_user
from tests.builders import signed_webhook
from tests.metrics import metric_value
from ticketrush import system_metrics


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _close_the_gateway_circuit():
    yield
    payment_services.gateway_breaker.record_success()


@pytest.fixture
def api():
    client = APIClient()
    client.force_authenticate(make_user())
    return client


def _hold(api, event, key, quantity=1):
    return api.post(f'/api/events/{event.uuid}/holds/', {'quantity': quantity}, format='json', headers={'Idempotency-Key': key})


def _delta(reader, name, action, **attributes) -> float:
    before = metric_value(reader, name, **attributes)
    action()
    return metric_value(reader, name, **attributes) - before


def test_hold_requests_are_counted_by_result(api, metrics_reader):
    event = make_event(capacity=1, max_per_user=1)

    assert _delta(metrics_reader, 'ticketrush.hold.requests', lambda: _hold(api, event, 'a'), result='ok') == 1
    assert _delta(metrics_reader, 'ticketrush.hold.requests', lambda: _hold(api, event, 'a'), result='replayed') == 1
    assert _delta(metrics_reader, 'ticketrush.hold.requests', lambda: _hold(api, event, 'b'), result='sold_out') == 1


def test_gateway_charges_are_counted_by_outcome(metrics_reader):
    payment = payment_services.prepare_checkout(user=(hold := make_hold()).user, hold_uuid=hold.uuid)

    def fail_charge():
        with mock.patch('mockgateway.services.create_charge', side_effect=GatewayError('down')), pytest.raises(PaymentsUnavailable):
            payment_services.submit_charge(payment)

    durations_before = metric_value(metrics_reader, 'ticketrush.gateway.charge.duration', outcome='error')
    assert _delta(metrics_reader, 'ticketrush.gateway.charges', fail_charge, outcome='error') == payment_services.GATEWAY_ATTEMPTS
    assert metric_value(metrics_reader, 'ticketrush.gateway.charge.duration', outcome='error') - durations_before == payment_services.GATEWAY_ATTEMPTS

    with mock.patch.object(payment_services.gateway_breaker, 'allow', return_value=False):
        assert _delta(metrics_reader, 'ticketrush.gateway.charges', fail_charge, outcome='circuit_open') == 1

    assert _delta(metrics_reader, 'ticketrush.gateway.charges', lambda: payment_services.submit_charge(payment), outcome='ok') == 1


def test_webhooks_are_counted_by_result(metrics_reader, django_capture_on_commit_callbacks):
    body, headers = signed_webhook({'id': 'evt_metrics', 'type': 'charge.refunded', 'data': {'charge_id': 'c', 'idempotency_key': 'k'}})

    def post():
        APIClient().post('/api/webhooks/mock/', data=body, content_type='application/json', headers=headers)

    def post_unsigned():
        APIClient().post('/api/webhooks/mock/', data=body, content_type='application/json', headers={'Mock-Signature': 't=1,v1=0'})

    assert _delta(metrics_reader, 'ticketrush.webhooks.received', post, provider='mock', result='accepted') == 1
    assert _delta(metrics_reader, 'ticketrush.webhooks.received', post, provider='mock', result='duplicate') == 1
    assert _delta(metrics_reader, 'ticketrush.webhooks.received', post_unsigned, provider='mock', result='rejected') == 1


def test_task_outcomes_count_the_returned_value(metrics_reader):
    def run():
        with mock.patch('payments.services.apply_charge_succeeded', return_value='duplicate'):
            process_succeeded.apply(kwargs={'webhook_event_id': 1})

    assert _delta(metrics_reader, 'ticketrush.task.outcomes', run, task='payments.process_succeeded', outcome='duplicate') == 1


def test_a_dead_letter_is_counted_as_a_task_outcome(metrics_reader):
    def exhaust():
        process_succeeded.apply(kwargs={'webhook_event_id': 999_999}, retries=process_succeeded.max_retries, throw=False)

    assert _delta(metrics_reader, 'ticketrush.task.outcomes', exhaust, task='payments.process_succeeded', outcome='dead_letter') == 1


@pytest.fixture(autouse=True)
def _keep_the_test_transaction():
    # The reader thread reconnects between readings; inside a test transaction that would close the connection.
    with mock.patch.object(system_metrics, 'close_old_connections'):
        yield


def _observe(callback) -> list[tuple[float, dict]]:
    return [(observation.value, dict(observation.attributes or {})) for observation in callback(None)]


def test_outbox_age_reports_the_oldest_unpublished_row():
    stuck = OutboxMessage.objects.create(topic='notify.send_ticket_email', payload={})
    OutboxMessage.objects.filter(pk=stuck.pk).update(created_on=timezone.now() - timedelta(seconds=90))
    published = OutboxMessage.objects.create(topic='notify.send_ticket_email', payload={}, published_at=timezone.now())
    OutboxMessage.objects.filter(pk=published.pk).update(created_on=timezone.now() - timedelta(hours=1))

    [(age, _)] = _observe(system_metrics.outbox_oldest_age)

    assert 90 <= age < 120
    assert _observe(system_metrics.outbox_unpublished) == [(1, {})]


def test_outbox_age_is_zero_when_everything_is_published():
    assert _observe(system_metrics.outbox_oldest_age) == [(0, {})]


def test_only_unreplayed_dead_letters_are_pending():
    DeadLetter.objects.create(task_name='notify.send_ticket_email', error='x')
    DeadLetter.objects.create(task_name='notify.send_ticket_email', error='x', replayed_at=timezone.now())

    assert _observe(system_metrics.dead_letters_pending) == [(1, {})]


def test_stock_is_reported_for_published_events_in_their_sale_window():
    now = timezone.now()
    on_sale = make_event(title='On sale', capacity=10)
    sold_out = make_event(title='Sold out', capacity=5, available=0)
    make_event(title='Upcoming', sale_opens_at=now + timedelta(hours=1), sale_closes_at=now + timedelta(hours=2))
    make_event(title='Closed', sale_opens_at=now - timedelta(hours=2), sale_closes_at=now - timedelta(hours=1))
    make_event(title='Draft', is_published=False)

    assert sorted(_observe(system_metrics.events_available), key=lambda point: point[0]) == [
        (0, {'event': str(sold_out.uuid)}),
        (10, {'event': str(on_sale.uuid)}),
    ]


def test_stock_series_are_capped():
    for number in range(system_metrics.MAX_EVENTS_REPORTED + 3):
        make_event(title=f'Event {number}')

    assert len(_observe(system_metrics.events_available)) == system_metrics.MAX_EVENTS_REPORTED


def test_queue_lengths_include_the_priority_lists():
    lengths = {'critical': 2, 'critical\x06\x163': 1, 'bulk': 4}
    broker = mock.Mock(llen=lambda key: lengths.get(key, 0))

    with mock.patch.object(system_metrics, '_broker', return_value=broker):
        assert _observe(system_metrics.queue_lengths) == [(3, {'queue': 'critical'}), (4, {'queue': 'bulk'})]


def test_beat_publish_age_restarts_when_beat_sends_a_task():
    with mock.patch.object(system_metrics.time, 'monotonic', return_value=1000.0):
        system_metrics._mark_publish()
    with mock.patch.object(system_metrics.time, 'monotonic', return_value=1012.5):
        assert _observe(system_metrics.beat_publish_age) == [(12.5, {})]
