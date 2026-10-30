from collections import Counter
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import User
from audit.constants import ActivityVerb
from audit.models import ActivityLog
from mockgateway.models import MockCharge
from payments.models import Payment
from payments.models import Ticket
from payments.models import WebhookEvent
from tests.builders import make_event
from tests.builders import make_hold
from tests.builders import make_user
from ticketing.mockdata import MEDIUM_EVENT_MAX_CAPACITY
from ticketing.mockdata import MOCK_EVENTS
from ticketing.mockdata import MOCK_ORGANIZER_USERNAME
from ticketing.mockdata import purge_mockdata
from ticketing.mockdata import seed_mockdata
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.models import Order


pytestmark = pytest.mark.django_db


def _mock_event(title: str) -> Event:
    return Event.objects.get(organizer__username=MOCK_ORGANIZER_USERNAME, title=title)


def _buy(event: Event, user: User) -> Order:
    hold = make_hold(user=user, event=event)
    order = Order.objects.create(hold=hold, amount_satang=event.price_satang, status=Order.Status.PAID)
    payment = Payment.objects.create(
        order=order, provider='mock', amount_satang=order.amount_satang, expires_at=timezone.now() + timedelta(minutes=10)
    )
    Ticket.objects.create(order=order, seq=1, code=f'code-{payment.uuid}')
    WebhookEvent.objects.create(
        provider='mock', provider_event_id=f'evt-{payment.uuid}', event_type='charge.succeeded', payment_key=str(payment.uuid), payload={}
    )
    MockCharge.objects.create(idempotency_key=str(payment.uuid), amount_satang=order.amount_satang, expires_at=payment.expires_at)
    return order


def test_catalog_has_ten_to_fifteen_small_and_medium_events_four_to_three_across_every_sale_status():
    sizes = Counter('small' if spec.is_small else 'medium' for spec in MOCK_EVENTS)
    assert sizes['small'] * 3 == sizes['medium'] * 4
    assert 10 <= len(MOCK_EVENTS) <= 15
    assert max(spec.capacity for spec in MOCK_EVENTS) <= MEDIUM_EVENT_MAX_CAPACITY
    for is_small in (True, False):
        statuses = {spec.sale for spec in MOCK_EVENTS if spec.is_small == is_small and spec.published}
        assert statuses == set(Event.SaleStatus)
        assert any(not spec.published for spec in MOCK_EVENTS if spec.is_small == is_small)
    assert len({spec.title for spec in MOCK_EVENTS}) == len(MOCK_EVENTS)


def test_seeded_events_report_their_declared_sale_status():
    seed_mockdata()
    now = timezone.now()
    for spec in MOCK_EVENTS:
        event = _mock_event(spec.title)
        assert event.sale_status(now) == spec.sale, spec.title
        assert event.is_published == spec.published


def test_seed_is_idempotent_and_leaves_existing_events_untouched():
    first = seed_mockdata()
    event = _mock_event(MOCK_EVENTS[0].title)
    Event.objects.filter(pk=event.pk).update(available=event.available - 1)

    second = seed_mockdata()

    assert (first.events_created, second.events_created, second.events_existing) == (len(MOCK_EVENTS), 0, len(MOCK_EVENTS))
    assert Event.objects.filter(organizer__username=MOCK_ORGANIZER_USERNAME).count() == len(MOCK_EVENTS)
    assert _mock_event(MOCK_EVENTS[0].title).available == event.available - 1
    assert ActivityLog.objects.filter(verb=ActivityVerb.MOCKDATA_SEEDED).count() == 2


def test_seed_creates_buyers_that_can_sign_in_and_have_no_email():
    seed_mockdata(buyers=3, buyer_password='load-test-password-1')
    result = seed_mockdata(buyers=5, buyer_password='load-test-password-1')

    assert (result.buyers_created, result.buyers_existing) == (2, 3)
    buyers = User.objects.filter(username__startswith='mock-buyer-')
    assert buyers.count() == 5
    assert set(buyers.values_list('email', 'role')) == {('', User.Role.BUYER)}
    assert buyers.get(username='mock-buyer-00005').check_password('load-test-password-1')
    assert not User.objects.get(username=MOCK_ORGANIZER_USERNAME).has_usable_password()


def test_purge_deletes_mock_events_with_their_purchases_and_keeps_real_data():
    seed_mockdata(buyers=2, buyer_password='load-test-password-1')
    mock_buyer, loyal_buyer = User.objects.filter(username__startswith='mock-buyer-').order_by('username')
    real_buyer = make_user(username='mock-lookalike', email='real@example.com')
    real_event = make_event(title='Real show', max_per_user=4)
    flash = _mock_event('Flash Drop: 100 Seats')
    _buy(flash, mock_buyer)
    _buy(flash, real_buyer)
    real_order = _buy(real_event, real_buyer)
    _buy(real_event, loyal_buyer)

    deleted = purge_mockdata()

    assert not Event.objects.filter(organizer__username=MOCK_ORGANIZER_USERNAME).exists()
    assert list(Event.objects.all()) == [real_event]
    assert set(Order.objects.all()) == {real_order, Order.objects.get(hold__user=loyal_buyer)}
    assert (
        Hold.objects.count() == Payment.objects.count() == Ticket.objects.count() == WebhookEvent.objects.count() == MockCharge.objects.count() == 2
    )
    assert set(User.objects.filter(username__startswith='mock-').values_list('username', flat=True)) == {'mock-lookalike', loyal_buyer.username}
    assert deleted | {'events': 0} == {
        'tickets': 2,
        'webhook_events': 2,
        'mock_charges': 2,
        'payments': 2,
        'orders': 2,
        'holds': 2,
        'events': 0,
        'users': 2,
        'users_kept': 1,
    }
    assert deleted['events'] == len(MOCK_EVENTS)
    assert ActivityLog.objects.filter(verb=ActivityVerb.MOCKDATA_PURGED).get().detail == deleted | {'dry_run': False}


def test_purge_then_seed_restores_the_catalog():
    seed_mockdata()
    _buy(_mock_event('Flash Drop: 100 Seats'), make_user())
    purge_mockdata()

    assert seed_mockdata().events_created == len(MOCK_EVENTS)
    assert _mock_event('Flash Drop: 100 Seats').available == 100


def test_dry_run_reports_counts_and_deletes_nothing():
    seed_mockdata()
    _buy(_mock_event('Flash Drop: 100 Seats'), make_user())

    deleted = purge_mockdata(dry_run=True)

    assert (deleted['events'], deleted['orders'], deleted['users']) == (len(MOCK_EVENTS), 1, 1)
    assert Event.objects.count() == len(MOCK_EVENTS)
    assert Order.objects.count() == 1
    assert not ActivityLog.objects.filter(verb=ActivityVerb.MOCKDATA_PURGED).exists()


def test_purge_command_requires_confirmation(monkeypatch):
    seed_mockdata()
    monkeypatch.setattr('builtins.input', lambda prompt: 'no')

    with pytest.raises(CommandError):
        call_command('purge_mockdata')
    assert Event.objects.count() == len(MOCK_EVENTS)

    call_command('purge_mockdata', '--yes')
    assert not Event.objects.exists()


def test_seed_command_rejects_a_weak_buyer_password():
    with pytest.raises(CommandError):
        call_command('seed_mockdata', '--buyers', '2', '--buyer-password', '123')
    assert not User.objects.exists()

    call_command('seed_mockdata', '--buyers', '2', '--buyer-password', 'load-test-password-1')
    assert User.objects.filter(username__startswith='mock-buyer-').count() == 2
