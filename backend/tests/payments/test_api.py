from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from mockgateway.models import FaultConfig
from mockgateway.models import MockCharge
from payments import services as payment_services
from payments.models import Payment
from payments.models import Ticket
from payments.models import WebhookEvent
from reliability.models import OutboxMessage
from tests.builders import make_event
from tests.builders import make_hold
from tests.builders import make_user
from tests.builders import signed_webhook


pytestmark = pytest.mark.django_db


@pytest.fixture
def buyer():
    return make_user()


@pytest.fixture
def api(buyer):
    client = APIClient()
    client.force_authenticate(buyer)
    return client


def _checkout(api, hold, key='checkout-1'):
    headers = {'Idempotency-Key': key} if key is not None else {}
    return api.post(f'/api/holds/{hold.uuid}/checkout/', headers=headers)


def _post_webhook(event: dict, *, provider='mock', timestamp=None):
    body, headers = signed_webhook(event, timestamp=timestamp)
    return APIClient().post(f'/api/webhooks/{provider}/', data=body, content_type='application/json', headers=headers)


def _event(payment_key='00000000-0000-0000-0000-000000000000', event_id='evt_1', event_type='charge.succeeded'):
    return {'id': event_id, 'type': event_type, 'data': {'charge_id': 'chrg_mock_x', 'idempotency_key': payment_key}}


def test_checkout_returns_the_order_with_its_payment_link(api, buyer):
    hold = make_hold(user=buyer)

    response = _checkout(api, hold)

    assert response.status_code == 201
    data = response.json()['data']
    assert (data['hold'], data['status'], data['quantity']) == (str(hold.uuid), 'pending_payment', 1)
    assert data['payment']['status'] == 'pending'
    assert data['payment']['payment_url']
    assert 'id' not in data


def test_checkout_requires_an_idempotency_key(api, buyer):
    response = _checkout(api, make_hold(user=buyer), key=None)

    assert response.status_code == 400
    assert response.json()['status']['code'] == 'IDEMPOTENCY_KEY_REQUIRED'


def test_a_repeated_checkout_key_replays_the_first_response(api, buyer):
    hold = make_hold(user=buyer)
    first = _checkout(api, hold)

    second = _checkout(api, hold)

    assert second.headers['Idempotent-Replayed'] == 'true'
    assert second.json() == first.json()


def test_a_gateway_outage_is_reported_as_payments_unavailable(api, buyer):
    FaultConfig.objects.update_or_create(pk=1, defaults={'error_rate': 1.0})

    response = _checkout(api, make_hold(user=buyer))

    assert response.status_code == 503
    assert response.json()['status']['code'] == 'PAYMENTS_UNAVAILABLE'


def test_an_order_is_visible_to_its_buyer_only(api, buyer):
    order_uuid = _checkout(api, make_hold(user=buyer)).json()['data']['uuid']
    intruder = APIClient()
    intruder.force_authenticate(make_user(username='intruder'))

    assert api.get(f'/api/orders/{order_uuid}/').status_code == 200
    assert intruder.get(f'/api/orders/{order_uuid}/').status_code == 404


def test_a_webhook_with_a_bad_signature_is_rejected_before_anything_is_stored():
    response = APIClient().post('/api/webhooks/mock/', data=b'{}', content_type='application/json', headers={'Mock-Signature': 't=1,v1=0'})

    assert response.status_code == 401
    assert response.json()['status']['code'] == 'INVALID_SIGNATURE'
    assert not WebhookEvent.objects.exists()


def test_a_replayed_webhook_outside_the_tolerance_is_rejected():
    assert _post_webhook(_event(), timestamp=1).status_code == 401


def test_a_webhook_for_another_provider_is_not_found():
    assert _post_webhook(_event(), provider='omise').status_code == 404


def test_a_webhook_is_stored_once_and_queued_once():
    with mock.patch('payments.tasks.process_succeeded.apply_async'):
        first = _post_webhook(_event())
        second = _post_webhook(_event())

    assert (first.status_code, second.status_code) == (200, 200)
    assert WebhookEvent.objects.count() == 1
    assert list(OutboxMessage.objects.values_list('topic', flat=True)) == ['payments.process_succeeded']


def test_an_unhandled_event_type_is_stored_without_queuing_work():
    assert _post_webhook(_event(event_type='charge.refunded')).status_code == 200

    assert WebhookEvent.objects.count() == 1
    assert not OutboxMessage.objects.exists()


def test_a_purchase_from_hold_to_tickets_survives_duplicate_webhooks(api, buyer, django_capture_on_commit_callbacks):
    event = make_event(max_per_user=2)
    FaultConfig.objects.update_or_create(pk=1, defaults={'duplicate_webhook_rate': 1.0})
    hold = api.post(f'/api/events/{event.uuid}/holds/', {'quantity': 2}, format='json', headers={'Idempotency-Key': 'hold-1'}).json()['data']
    order = api.post(f'/api/holds/{hold["uuid"]}/checkout/', headers={'Idempotency-Key': 'checkout-1'}).json()['data']
    charge = MockCharge.objects.get()

    def deliver(webhook):
        body, headers = signed_webhook(webhook)
        assert APIClient().post('/api/webhooks/mock/', data=body, content_type='application/json', headers=headers).status_code == 200

    with mock.patch('mockgateway.tasks.post_event', side_effect=deliver), django_capture_on_commit_callbacks(execute=True):
        assert APIClient().post(f'/mock-gateway/charges/{charge.charge_id}/pay/', {'outcome': 'succeeded'}, format='json').status_code == 200

    assert api.get(f'/api/orders/{order["uuid"]}/').json()['data']['status'] == 'paid'
    tickets = api.get('/api/me/tickets/').json()
    assert tickets['count'] == 2
    assert {ticket['event']['uuid'] for ticket in tickets['data']} == {str(event.uuid)}
    assert Ticket.objects.count() == 2


def test_my_tickets_lists_only_my_own(api):
    other = make_user(username='other')
    make_hold(user=other)

    response = api.get('/api/me/tickets/')

    assert response.status_code == 200
    assert response.json()['count'] == 0


def _paid_order(user, *, quantity=1):
    hold = make_hold(user=user, event=make_event(title='Paid show', venue_name='Hall A'), quantity=quantity)
    payment = payment_services.submit_charge(payment_services.prepare_checkout(user=user, hold_uuid=hold.uuid))
    webhook = WebhookEvent.objects.create(
        provider='mock',
        provider_event_id=f'evt_{payment.uuid}',
        event_type='charge.succeeded',
        payment_key=str(payment.uuid),
        payload={'id': f'evt_{payment.uuid}', 'type': 'charge.succeeded', 'data': {'idempotency_key': str(payment.uuid)}},
    )
    assert payment_services.apply_charge_succeeded(webhook_event_id=webhook.pk) == 'paid'
    return Payment.objects.get(pk=payment.pk).order


def test_my_orders_lists_my_orders_with_event_and_tickets(api, buyer):
    order = _paid_order(buyer, quantity=2)
    make_hold(user=make_user(username='other'))

    response = api.get('/api/me/orders/')

    assert response.status_code == 200
    body = response.json()
    assert body['count'] == 1
    data = body['data'][0]
    assert data['uuid'] == str(order.uuid)
    assert data['status'] == 'paid'
    assert (data['event']['title'], data['event']['venue_name']) == ('Paid show', 'Hall A')
    assert [ticket['seq'] for ticket in data['tickets']] == [1, 2]
    assert data['payment']['status'] == 'succeeded'


def test_my_orders_queries_do_not_grow_with_the_order_count(api, buyer, django_assert_max_num_queries):
    _paid_order(buyer)
    with CaptureQueriesContext(connection) as one:
        api.get('/api/me/orders/')
    _paid_order(buyer)
    _paid_order(buyer)

    with django_assert_max_num_queries(len(one.captured_queries)):
        response = api.get('/api/me/orders/')

    assert response.json()['count'] == 3


def test_my_orders_requires_sign_in():
    assert APIClient().get('/api/me/orders/').status_code == 401
