"""Races run on real threads and connections; each test commits, so the database is flushed afterwards."""

import pytest

from mockgateway.models import MockCharge
from payments import services
from payments.models import Payment
from tests.builders import make_event
from tests.builders import make_hold
from tests.concurrency import outcome
from tests.concurrency import race
from ticketing import services as ticketing
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.models import Order


pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_checkouts_of_one_hold_create_one_order_and_one_charge():
    hold = make_hold()

    def checkout():
        return services.submit_charge(services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid)).pk

    results = race([checkout] * 6)

    assert len(set(results)) == 1
    assert Order.objects.count() == 1
    assert Payment.objects.count() == 1
    assert MockCharge.objects.count() == 1


def test_checkout_and_release_racing_on_one_hold_cannot_both_win():
    event = make_event(capacity=5)
    hold = make_hold(event=event, quantity=2)

    results = race(
        [
            lambda: services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid),
            lambda: ticketing.release_hold(user=hold.user, hold_uuid=hold.uuid),
        ]
    )

    checkout, release = map(outcome, results)
    assert (checkout, release) in {('ok', 'HoldHasOrder'), ('HoldNotActive', 'ok')}
    released = Hold.objects.get(pk=hold.pk).status == Hold.Status.RELEASED
    assert Order.objects.exists() is not released
    assert Event.objects.get(pk=event.pk).available == (5 if released else 3)
