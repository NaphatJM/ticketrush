import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from mockgateway import services as mock_gateway
from mockgateway.models import MockCharge
from payments import services as payments
from payments.models import Payment
from payments.models import Ticket
from payments.models import WebhookEvent
from reliability.models import DeadLetter
from reliability.models import OutboxMessage
from tests.builders import make_hold
from tests.builders import make_user
from ticketing.loadtest import SAMPLE_FIELDS
from ticketing.loadtest import sample_saturation
from ticketing.loadtest import seed_loadtest_event
from ticketing.loadtest import verify_event
from ticketing.mockdata import MOCK_ORGANIZER_USERNAME
from ticketing.mockdata import purge_mockdata
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.models import Order


pytestmark = pytest.mark.django_db


def _pay(hold: Hold, *, event_id: str) -> Payment:
    payment = payments.submit_charge(payments.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))
    charge = MockCharge.objects.get(charge_id=payment.provider_charge_id)
    charge.status = MockCharge.Status.SUCCEEDED
    payload = mock_gateway.build_event(charge) | {'id': event_id}
    webhook = WebhookEvent.objects.create(
        provider='mock', provider_event_id=event_id, event_type=payload['type'], payment_key=str(payment.uuid), payload=payload
    )
    payments.apply_charge_succeeded(webhook_event_id=webhook.pk)
    OutboxMessage.objects.update(published_at=timezone.now())
    return payment


def _charge_again(payment: Payment) -> Payment:
    return Payment.objects.create(
        order=payment.order, provider='mock', status=Payment.Status.SUCCEEDED, amount_satang=payment.amount_satang, expires_at=payment.expires_at
    )


def _charge_without_webhook(hold: Hold) -> None:
    payment = payments.submit_charge(payments.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))
    MockCharge.objects.filter(idempotency_key=str(payment.uuid)).update(status=MockCharge.Status.SUCCEEDED)


def _outbox_row(*, age: timedelta) -> OutboxMessage:
    message = OutboxMessage.objects.create(topic='notify.send_ticket_email')
    OutboxMessage.objects.filter(pk=message.pk).update(created_on=timezone.now() - age)
    return message


@pytest.fixture
def sold_event() -> Event:
    event = seed_loadtest_event(scenario='journey', capacity=10, max_per_user=2, opens_in=timedelta(0))
    _pay(make_hold(event=event, quantity=2), event_id='evt_1')
    make_hold(event=event, quantity=1)
    return event


class FakeRedis:
    def __init__(self, lengths: dict[str, int]):
        self.lengths = lengths

    def llen(self, key: str) -> int:
        return self.lengths.get(key, 0)


def test_seed_creates_a_published_mock_event_that_purge_removes():
    now = timezone.now()
    event = seed_loadtest_event(scenario='flash', now=now)

    assert event.organizer.username == MOCK_ORGANIZER_USERNAME
    assert (event.capacity, event.available, event.max_per_user, event.is_published) == (100, 100, 2, True)
    assert event.sale_opens_at == now + timedelta(minutes=5)
    assert event.sale_status(now) == Event.SaleStatus.UPCOMING

    purge_mockdata()
    assert not Event.objects.filter(pk=event.pk).exists()


def test_seed_command_prints_the_event_uuid_for_locust(capsys):
    call_command('seed_loadtest', '--scenario', 'flash', '--capacity', '7', '--opens-in', '30')

    event = Event.objects.get()
    assert (event.capacity, event.available) == (7, 7)
    assert f'LOADTEST_EVENT={event.uuid}' in capsys.readouterr().out


def test_verify_passes_on_a_consistent_event(sold_event):
    report = verify_event(sold_event)

    assert report['ok'], report['checks']
    assert report['stock'] == {'capacity': 10, 'available': 7, 'held': 3}
    assert report['tickets'] == 2
    assert report['orders'] == {'paid': 1}


@pytest.mark.parametrize(
    ('corrupt', 'failed'),
    [
        (lambda event: Event.objects.filter(pk=event.pk).update(available=8), 'stock_balanced'),
        (lambda event: Ticket.objects.filter(seq=2).delete(), 'paid_orders_fully_ticketed'),
        (lambda event: Hold.objects.filter(event=event, quantity=1).update(user=Hold.objects.get(quantity=2).user), 'within_per_user_limit'),
        (lambda event: _charge_again(Payment.objects.get()), 'single_successful_payment_per_order'),
        (lambda event: WebhookEvent.objects.update(processed_at=None), 'webhooks_processed'),
        (lambda event: Hold.objects.filter(quantity=2).update(status=Hold.Status.ACTIVE), 'paid_orders_converted'),
        (lambda event: Hold.objects.filter(quantity=1).update(status=Hold.Status.CONVERTED), 'converted_holds_paid'),
        (lambda event: Order.objects.create(hold=Hold.objects.get(quantity=1), amount_satang=1, status='paid_unfulfilled'), 'no_paid_unfulfilled'),
        (lambda event: _outbox_row(age=timedelta(minutes=1)), 'outbox_drained'),
        (lambda event: DeadLetter.objects.create(task_name='tickets.issue', error='boom'), 'no_dead_letters'),
        (lambda event: _charge_without_webhook(Hold.objects.get(quantity=1)), 'charges_recorded'),
    ],
)
def test_verify_reports_each_broken_invariant(sold_event, corrupt, failed):
    corrupt(sold_event)

    report = verify_event(sold_event)

    assert not report['ok']
    assert [name for name, ok in report['checks'].items() if not ok] == [failed]


def test_verify_allows_rows_the_relay_has_not_reached_yet(sold_event):
    _outbox_row(age=timedelta(seconds=1))

    assert verify_event(sold_event)['ok']


def test_verify_limit_ignores_expired_holds_the_sweeper_has_not_reached(sold_event):
    buyer = Hold.objects.get(quantity=2).user
    Hold.objects.filter(quantity=1).update(user=buyer, expires_at=timezone.now() - timedelta(seconds=1))

    assert verify_event(sold_event)['checks']['within_per_user_limit']


@pytest.mark.django_db(transaction=True)
def test_verify_runs_in_its_own_read_only_snapshot_outside_a_transaction():
    event = seed_loadtest_event(scenario='journey', capacity=5)

    assert verify_event(event)['ok']


def test_verify_ignores_dead_letters_before_the_run():
    event = seed_loadtest_event(scenario='journey', capacity=5)
    DeadLetter.objects.create(task_name='tickets.issue', error='old')

    assert verify_event(event, since=timezone.now()).get('ok')


def test_verify_command_exits_nonzero_when_a_check_fails(sold_event, capsys):
    Event.objects.filter(pk=sold_event.pk).update(available=0)

    with pytest.raises(CommandError) as raised:
        call_command('loadtest_verify', '--event', str(sold_event.uuid))

    assert raised.value.returncode == 1
    assert 'stock_balanced' in str(raised.value)
    assert json.loads(capsys.readouterr().out)['stock']['available'] == 0


def test_verify_command_rejects_a_since_without_offset(sold_event):
    with pytest.raises(CommandError, match='UTC offset'):
        call_command('loadtest_verify', '--event', str(sold_event.uuid), '--since', '2026-10-30T14:00:00')


def test_verify_command_rejects_an_unknown_event():
    with pytest.raises(CommandError, match='No event'):
        call_command('loadtest_verify', '--event', 'not-a-uuid')


def test_sample_reads_connections_and_counts_every_priority_list_of_a_queue():
    make_user()
    OutboxMessage.objects.create(topic='notify.send_ticket_email')

    row = sample_saturation(FakeRedis({'critical': 3, 'critical\x06\x169': 2, 'gateway': 4, 'bulk': 1}))

    assert tuple(row) == SAMPLE_FIELDS
    assert (row['queue_critical'], row['queue_gateway'], row['queue_bulk'], row['outbox_unpublished']) == (5, 4, 1, 1)
    assert 1 <= row['db_connections'] <= row['db_max_connections']
