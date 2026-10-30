"""Races run on real threads and connections; each test commits, so the database is flushed afterwards."""

import threading
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

import pytest
from django.db import connection
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from reliability.services import run_idempotent
from tests.builders import make_event
from tests.builders import make_user
from tests.concurrency import outcome
from tests.concurrency import race
from ticketing import services
from ticketing.exceptions import SaleNotOpen
from ticketing.exceptions import SoldOut
from ticketing.models import Event
from ticketing.models import Hold


pytestmark = pytest.mark.django_db(transaction=True)


def test_many_buyers_racing_for_few_seats_never_oversell():
    event = make_event(capacity=10, max_per_user=1)
    buyers = [make_user(username=f'buyer-{n}') for n in range(40)]

    results = race([lambda user=user: services.create_hold(user=user, event_uuid=event.uuid, quantity=1) for user in buyers])

    assert Counter(map(outcome, results)) == {'ok': 10, 'SoldOut': 30}
    assert Event.objects.get(pk=event.pk).available == 0
    assert Hold.objects.filter(event=event).aggregate(total=Sum('quantity'))['total'] == 10


@contextmanager
def event_row_locked_elsewhere(event: Event):
    """Hold the event's row lock on another connection, as a winning buyer does until their hold commits."""
    locked = threading.Event()
    release = threading.Event()

    def hold_lock():
        try:
            with transaction.atomic():
                Event.objects.select_for_update().get(pk=event.pk)
                locked.set()
                release.wait(timeout=30)
        finally:
            connection.close()

    locker = threading.Thread(target=hold_lock)
    locker.start()
    try:
        assert locked.wait(timeout=5)
        yield
    finally:
        release.set()
        locker.join()


@contextmanager
def lock_timeout(value: str):
    with connection.cursor() as cursor:
        cursor.execute(f"SET lock_timeout = '{value}'")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SET lock_timeout = DEFAULT')


@pytest.mark.parametrize(
    ('available', 'opens', 'closes', 'error'),
    [
        (0, -timedelta(minutes=1), timedelta(hours=1), SoldOut),
        (0, timedelta(minutes=5), timedelta(hours=1), SaleNotOpen),
        (0, -timedelta(hours=2), -timedelta(hours=1), SaleNotOpen),
        (5, -timedelta(hours=2), -timedelta(hours=1), SaleNotOpen),
    ],
    ids=['sold-out', 'sold-out-not-yet-open', 'sold-out-closed', 'closed'],
)
def test_a_hold_that_cannot_succeed_is_refused_without_waiting_for_the_event_row_lock(available, opens, closes, error):
    now = timezone.now()
    event = make_event(capacity=5, available=available, sale_opens_at=now + opens, sale_closes_at=now + closes)
    user = make_user()

    # Waiting on the lock would raise LockNotAvailable instead of the expected refusal.
    with event_row_locked_elsewhere(event), lock_timeout('2s'), pytest.raises(error):
        services.create_hold(user=user, event_uuid=event.uuid, quantity=1)

    assert Event.objects.get(pk=event.pk).available == available
    assert not Hold.objects.exists()


def test_one_buyer_racing_with_themselves_stays_within_the_per_user_limit():
    event = make_event(capacity=20, max_per_user=2)
    user = make_user()

    results = race([lambda: services.create_hold(user=user, event_uuid=event.uuid, quantity=1)] * 10)

    assert Counter(map(outcome, results)) == {'ok': 2, 'PerUserLimit': 8}
    assert Event.objects.get(pk=event.pk).available == 18


def test_duplicate_requests_with_one_key_create_one_hold():
    event = make_event(capacity=10)
    user = make_user()

    def submit():
        return run_idempotent(
            user=user,
            key='double-click',
            endpoint='events.holds.create',
            payload={'event': str(event.uuid), 'quantity': 1},
            action=lambda: (201, {'uuid': str(services.create_hold(user=user, event_uuid=event.uuid, quantity=1).uuid)}),
        )

    results = race([submit] * 8)

    assert all(outcome(result) == 'ok' for result in results)
    assert len({result.body['uuid'] for result in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    assert Hold.objects.count() == 1


def test_release_and_sweeper_racing_on_one_hold_return_its_stock_once():
    event = make_event(capacity=5)
    user = make_user()
    hold = services.create_hold(user=user, event_uuid=event.uuid, quantity=2)
    later = timezone.now() + services.HOLD_TTL + timedelta(seconds=1)

    with mock.patch('django.utils.timezone.now', return_value=later):
        race([lambda: services.release_hold(user=user, hold_uuid=hold.uuid), services.expire_holds])

    assert Hold.objects.get(pk=hold.pk).status in {Hold.Status.RELEASED, Hold.Status.EXPIRED}
    assert Event.objects.get(pk=event.pk).available == 5
