import base64
import io
import json
import urllib.error
from unittest import mock

import pytest
from celery.exceptions import Retry
from django.test import override_settings

from mockgateway import services as mock_gateway
from mockgateway.models import MockCharge
from notify import resend
from notify import services
from notify.tasks import send_ticket_email
from payments import services as payments
from payments.models import Payment
from payments.models import WebhookEvent
from reliability.models import DeadLetter
from reliability.models import OutboxMessage
from tests.builders import make_event
from tests.builders import make_hold
from tests.builders import make_user
from ticketing.models import Event
from ticketing.models import Hold


pytestmark = pytest.mark.django_db

TOPIC = 'notify.send_ticket_email'


def _webhook(payment: Payment, *, succeeded: bool, event_id: str = 'evt_1') -> WebhookEvent:
    charge = MockCharge.objects.get(charge_id=payment.provider_charge_id)
    charge.status = MockCharge.Status.SUCCEEDED if succeeded else MockCharge.Status.FAILED
    payload = mock_gateway.build_event(charge) | {'id': event_id}
    return WebhookEvent.objects.create(
        provider='mock', provider_event_id=event_id, event_type=payload['type'], payment_key=str(payment.uuid), payload=payload
    )


def _checkout(hold) -> Payment:
    return payments.submit_charge(payments.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))


def _paid_order(*, quantity: int = 1, email: str = 'buyer@example.test', title: str = 'Launch night', **event_fields):
    hold = make_hold(user=make_user(email=email), event=make_event(max_per_user=3, title=title, **event_fields), quantity=quantity)
    payment = _checkout(hold)
    assert payments.apply_charge_succeeded(webhook_event_id=_webhook(payment, succeeded=True).pk) == 'paid'
    return payment.order


def test_paying_an_order_queues_its_ticket_email():
    order = _paid_order()

    assert OutboxMessage.objects.get(topic=TOPIC).payload == {'order_id': order.pk}


def test_a_duplicate_success_event_queues_no_second_email():
    order = _paid_order()

    assert payments.apply_charge_succeeded(webhook_event_id=_webhook(order.payments.get(), succeeded=True, event_id='evt_2').pk) == 'duplicate'

    assert OutboxMessage.objects.filter(topic=TOPIC).count() == 1


def test_a_failed_charge_queues_no_email():
    payment = _checkout(make_hold())

    payments.apply_charge_failed(webhook_event_id=_webhook(payment, succeeded=False).pk)

    assert not OutboxMessage.objects.filter(topic=TOPIC).exists()


def test_a_paid_but_unfulfilled_order_queues_no_email():
    hold = make_hold()
    payment = _checkout(hold)
    Hold.objects.filter(pk=hold.pk).update(status=Hold.Status.EXPIRED)
    Event.objects.filter(pk=hold.event_id).update(available=0)

    assert payments.apply_charge_succeeded(webhook_event_id=_webhook(payment, succeeded=True).pk) == 'unfulfilled'

    assert not OutboxMessage.objects.filter(topic=TOPIC).exists()


@override_settings(RESEND_API_KEY='re_test')
def test_the_email_carries_one_inline_qr_per_ticket_and_an_order_scoped_idempotency_key():
    order = _paid_order(quantity=2)

    with mock.patch('notify.resend.send_email', return_value='email-1') as send:
        assert services.send_ticket_email(order_id=order.pk) == 'sent'

    kwargs = send.call_args.kwargs
    assert kwargs['api_key'] == 're_test'
    assert kwargs['idempotency_key'] == f'ticket-email/{order.uuid}'
    message = kwargs['message']
    assert message['to'] == ['buyer@example.test']
    assert [attachment['content_id'] for attachment in message['attachments']] == ['ticket-1', 'ticket-2']
    assert all(base64.b64decode(attachment['content']).startswith(b'\x89PNG') for attachment in message['attachments'])
    assert 'src="cid:ticket-1"' in message['html']
    assert 'src="cid:ticket-2"' in message['html']
    assert all(code in message['text'] for code in order.tickets.values_list('code', flat=True))


@override_settings(RESEND_API_KEY='re_test')
def test_the_message_is_identical_on_every_retry():
    order = _paid_order(quantity=2)

    with mock.patch('notify.resend.send_email', return_value='email-1') as send:
        services.send_ticket_email(order_id=order.pk)
        services.send_ticket_email(order_id=order.pk)

    first, second = (call.kwargs for call in send.call_args_list)
    assert json.dumps(first) == json.dumps(second)


def test_the_html_body_shows_each_ticket_code_for_clients_that_block_images():
    order = _paid_order()

    message = services.build_ticket_email(order, list(order.tickets.all()), to='buyer@example.test')

    assert order.tickets.get().code in message['html']


def test_the_event_title_is_escaped_in_the_html_body():
    order = _paid_order(title='<script>alert(1)</script>')

    message = services.build_ticket_email(order, list(order.tickets.all()), to='buyer@example.test')

    assert '<script>' not in message['html']
    assert '&lt;script&gt;' in message['html']


IMPORTANT_INFO = 'Doors open 18:00\n<b>No bags</b>'


def test_the_email_describes_the_event_venue_and_order():
    order = _paid_order(
        quantity=2,
        price_satang=150_000,
        presented_by='Rush Live',
        banner_url='https://cdn.example.test/banner.jpg',
        venue_name='Impact Arena',
        venue_address='99 Popular Road',
        venue_map_url='https://maps.example.test/impact',
        important_info=IMPORTANT_INFO,
    )

    message = services.build_ticket_email(order, list(order.tickets.all()), to='buyer@example.test')

    html, text = message['html'], message['text']
    assert 'src="https://cdn.example.test/banner.jpg"' in html
    assert 'href="https://maps.example.test/impact"' in html
    for value in ('Rush Live', 'Impact Arena', '99 Popular Road', '2 &times; ticket at THB 1,500.00', 'THB 3,000.00', str(order.uuid)):
        assert value in html
    assert 'Doors open 18:00<br>&lt;b&gt;No bags&lt;/b&gt;' in html
    for value in ('Impact Arena', '2 x ticket at THB 1,500.00', 'Total paid: THB 3,000.00', IMPORTANT_INFO):
        assert value in text


def test_optional_event_sections_are_left_out_when_empty():
    order = _paid_order()

    message = services.build_ticket_email(order, list(order.tickets.all()), to='buyer@example.test')

    for marker in ('Presented by', 'Where', 'Open in maps', 'Good to know', '<img src="https'):
        assert marker not in message['html']
    for marker in ('WHERE', 'GOOD TO KNOW', 'Presented by'):
        assert marker not in message['text']


@override_settings(RESEND_API_KEY='')
def test_an_empty_api_key_sends_nothing():
    order = _paid_order()

    with mock.patch('notify.resend.send_email') as send:
        assert services.send_ticket_email(order_id=order.pk) == 'disabled'

    send.assert_not_called()


@override_settings(RESEND_API_KEY='re_test')
def test_a_buyer_without_an_address_is_skipped():
    order = _paid_order(email='')

    with mock.patch('notify.resend.send_email') as send:
        assert services.send_ticket_email(order_id=order.pk) == 'no_address'

    send.assert_not_called()


@override_settings(RESEND_API_KEY='re_test')
def test_a_transient_resend_failure_is_retried_without_a_dead_letter():
    order = _paid_order()

    with mock.patch('notify.resend.send_email', side_effect=resend.EmailUnavailableError('Resend 503')), pytest.raises(Retry):
        send_ticket_email.delay(order_id=order.pk)

    assert not DeadLetter.objects.exists()


@override_settings(RESEND_API_KEY='re_test')
def test_a_transient_failure_becomes_a_dead_letter_after_eight_retries():
    order = _paid_order()

    with mock.patch('notify.resend.send_email', side_effect=resend.EmailUnavailableError('Resend 503')):
        send_ticket_email.apply(kwargs={'order_id': order.pk}, retries=8, throw=False)

    letter = DeadLetter.objects.get()
    assert (letter.task_name, letter.args) == (TOPIC, {'order_id': order.pk})


@override_settings(RESEND_API_KEY='re_test')
def test_the_seventh_retry_still_schedules_an_eighth():
    order = _paid_order()

    # Eager mode runs the scheduled retry inline and re-raises its error, so retry 7 sends once more at retry 8.
    with (
        mock.patch('notify.resend.send_email', side_effect=resend.EmailUnavailableError('Resend 503')) as send,
        pytest.raises(resend.EmailUnavailableError),
    ):
        send_ticket_email.apply(kwargs={'order_id': order.pk}, retries=7, throw=False)

    assert send.call_count == 2


def test_sends_are_rate_limited_below_the_resend_team_limit():
    assert send_ticket_email.rate_limit == '5/s'


@override_settings(RESEND_API_KEY='re_test')
def test_a_rejected_message_is_dead_lettered_without_a_retry():
    order = _paid_order()

    with mock.patch('notify.resend.send_email', side_effect=resend.EmailRejectedError('Resend 403 validation_error')) as send:
        send_ticket_email.apply(kwargs={'order_id': order.pk}, throw=False)

    send.assert_called_once()
    assert 'EmailRejectedError' in DeadLetter.objects.get().error


def _http_error(code: int, name: str) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({'name': name, 'message': 'x'}).encode())
    return urllib.error.HTTPError(resend.API_URL, code, name, hdrs=None, fp=body)


def test_the_client_sends_the_idempotency_key_with_a_timeout():
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(b'{"id": "email-1"}')

    with mock.patch('urllib.request.urlopen', return_value=response) as urlopen:
        assert resend.send_email(api_key='re_test', message={'to': ['a@example.test']}, idempotency_key='ticket-email/1') == 'email-1'

    request = urlopen.call_args.args[0]
    assert request.get_header('Idempotency-key') == 'ticket-email/1'
    assert request.get_header('Authorization') == 'Bearer re_test'
    assert urlopen.call_args.kwargs['timeout'] == resend.TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ('error', 'expected'),
    [
        (_http_error(429, 'rate_limit_exceeded'), resend.EmailUnavailableError),
        (_http_error(429, 'daily_quota_exceeded'), resend.EmailRejectedError),
        (_http_error(429, 'monthly_quota_exceeded'), resend.EmailRejectedError),
        (_http_error(500, 'application_error'), resend.EmailUnavailableError),
        (_http_error(503, 'service_unavailable'), resend.EmailUnavailableError),
        (_http_error(409, 'concurrent_idempotent_requests'), resend.EmailUnavailableError),
        (_http_error(409, 'resource_locked'), resend.EmailUnavailableError),
        (_http_error(409, 'invalid_idempotent_request'), resend.EmailRejectedError),
        (_http_error(400, 'invalid_idempotency_key'), resend.EmailRejectedError),
        (_http_error(401, 'validation_error'), resend.EmailRejectedError),
        (_http_error(403, 'validation_error'), resend.EmailRejectedError),
        (_http_error(422, 'missing_required_field'), resend.EmailRejectedError),
        (urllib.error.URLError('connection refused'), resend.EmailUnavailableError),
        (TimeoutError('timed out'), resend.EmailUnavailableError),
    ],
)
def test_the_client_separates_retryable_failures_from_rejections(error, expected):
    with mock.patch('urllib.request.urlopen', side_effect=error), pytest.raises(expected):
        resend.send_email(api_key='re_test', message={}, idempotency_key='k')
