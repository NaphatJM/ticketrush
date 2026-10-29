"""Races run on real threads and connections; each test commits, so the database is flushed afterwards."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import mock

import pytest
from django.db import connection
from django.db.models import Sum
from django.utils import timezone

from reliability.services import run_idempotent
from tests.builders import make_event
from tests.builders import make_user
from ticketing import services
from ticketing.models import Event
from ticketing.models import Hold


pytestmark = pytest.mark.django_db(transaction=True)


def race(calls):
    """Start every call at the same moment, each on its own connection, and return each outcome."""
    barrier = threading.Barrier(len(calls))

    def run(call):
        try:
            barrier.wait()
            return call()
        except Exception as exc:
            return exc
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def _outcome(result) -> str:
    return type(result).__name__ if isinstance(result, Exception) else 'ok'


def test_many_buyers_racing_for_few_seats_never_oversell():
    event = make_event(capacity=10, max_per_user=1)
    buyers = [make_user(username=f'buyer-{n}') for n in range(40)]

    results = race([lambda user=user: services.create_hold(user=user, event_uuid=event.uuid, quantity=1) for user in buyers])

    assert Counter(map(_outcome, results)) == {'ok': 10, 'SoldOut': 30}
    assert Event.objects.get(pk=event.pk).available == 0
    assert Hold.objects.filter(event=event).aggregate(total=Sum('quantity'))['total'] == 10


def test_one_buyer_racing_with_themselves_stays_within_the_per_user_limit():
    event = make_event(capacity=20, max_per_user=2)
    user = make_user()

    results = race([lambda: services.create_hold(user=user, event_uuid=event.uuid, quantity=1)] * 10)

    assert Counter(map(_outcome, results)) == {'ok': 2, 'PerUserLimit': 8}
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

    assert all(_outcome(result) == 'ok' for result in results)
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
