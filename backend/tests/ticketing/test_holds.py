from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound

from audit.models import ActivityLog
from tests.builders import make_event
from tests.builders import make_user
from ticketing import services
from ticketing.exceptions import HoldHasOrder
from ticketing.exceptions import HoldNotActive
from ticketing.exceptions import PerUserLimit
from ticketing.exceptions import SaleNotOpen
from ticketing.exceptions import SoldOut
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.models import Order


pytestmark = pytest.mark.django_db


def freeze_time(moment):
    return mock.patch('django.utils.timezone.now', return_value=moment)


def _available(event: Event) -> int:
    return Event.objects.values_list('available', flat=True).get(pk=event.pk)


def test_a_hold_reserves_stock_until_it_expires():
    event = make_event(capacity=10)
    user = make_user()

    hold = services.create_hold(user=user, event_uuid=event.uuid, quantity=2)

    assert hold.status == Hold.Status.ACTIVE
    assert hold.expires_at - timezone.now() == pytest.approx(services.HOLD_TTL, abs=timedelta(seconds=5))
    assert _available(event) == 8


def test_a_hold_is_audited_with_its_actor():
    user = make_user()
    hold = services.create_hold(user=user, event_uuid=make_event().uuid, quantity=1)

    row = ActivityLog.objects.get(verb='hold.created')

    assert row.actor == user
    assert row.target_id == str(hold.uuid)


def test_a_request_larger_than_the_stock_is_sold_out_and_reserves_nothing():
    event = make_event(capacity=1, max_per_user=4)

    with pytest.raises(SoldOut):
        services.create_hold(user=make_user(), event_uuid=event.uuid, quantity=2)

    assert _available(event) == 1
    assert not Hold.objects.exists()


@pytest.mark.parametrize(
    ('opens', 'closes'),
    [(timedelta(minutes=5), timedelta(hours=1)), (-timedelta(hours=2), -timedelta(hours=1))],
    ids=['not-yet-open', 'already-closed'],
)
def test_no_hold_outside_the_sale_window(opens, closes):
    now = timezone.now()
    event = make_event(sale_opens_at=now + opens, sale_closes_at=now + closes)

    with pytest.raises(SaleNotOpen):
        services.create_hold(user=make_user(), event_uuid=event.uuid, quantity=1)

    assert _available(event) == event.capacity


def test_an_unknown_event_is_not_found():
    with pytest.raises(NotFound):
        services.create_hold(user=make_user(), event_uuid='00000000-0000-0000-0000-000000000000', quantity=1)


def test_a_single_request_above_the_per_user_limit_is_refused():
    event = make_event(max_per_user=2)

    with pytest.raises(PerUserLimit):
        services.create_hold(user=make_user(), event_uuid=event.uuid, quantity=3)


def test_the_per_user_limit_counts_active_and_converted_holds_and_returns_stock_on_refusal():
    event = make_event(capacity=10, max_per_user=2)
    user = make_user()
    services.create_hold(user=user, event_uuid=event.uuid, quantity=1)
    converted = services.create_hold(user=user, event_uuid=event.uuid, quantity=1)
    Hold.objects.filter(pk=converted.pk).update(status=Hold.Status.CONVERTED)

    with pytest.raises(PerUserLimit):
        services.create_hold(user=user, event_uuid=event.uuid, quantity=1)

    assert _available(event) == 8


def test_the_per_user_limit_ignores_holds_past_their_expiry_before_the_sweeper_runs():
    event = make_event(capacity=10, max_per_user=1)
    user = make_user()
    services.create_hold(user=user, event_uuid=event.uuid, quantity=1)

    with freeze_time(timezone.now() + services.HOLD_TTL + timedelta(seconds=1)):
        services.create_hold(user=user, event_uuid=event.uuid, quantity=1)

    assert Hold.objects.filter(user=user, status=Hold.Status.ACTIVE).count() == 2


def test_releasing_a_hold_returns_its_stock():
    event = make_event(capacity=5)
    user = make_user()
    hold = services.create_hold(user=user, event_uuid=event.uuid, quantity=2)

    released = services.release_hold(user=user, hold_uuid=hold.uuid)

    assert released.status == Hold.Status.RELEASED
    assert _available(event) == 5
    assert ActivityLog.objects.filter(verb='hold.released', target_id=str(hold.uuid)).exists()


def test_a_hold_is_released_only_once():
    event = make_event(capacity=5)
    user = make_user()
    hold = services.create_hold(user=user, event_uuid=event.uuid, quantity=2)
    services.release_hold(user=user, hold_uuid=hold.uuid)

    with pytest.raises(HoldNotActive):
        services.release_hold(user=user, hold_uuid=hold.uuid)

    assert _available(event) == 5


def test_another_users_hold_is_not_found():
    hold = services.create_hold(user=make_user(), event_uuid=make_event().uuid, quantity=1)

    with pytest.raises(NotFound):
        services.release_hold(user=make_user(username='intruder'), hold_uuid=hold.uuid)


def test_a_hold_with_an_order_cannot_be_released():
    event = make_event(capacity=5)
    user = make_user()
    hold = services.create_hold(user=user, event_uuid=event.uuid, quantity=1)
    Order.objects.create(hold=hold, amount_satang=event.price_satang)

    with pytest.raises(HoldHasOrder):
        services.release_hold(user=user, hold_uuid=hold.uuid)

    assert _available(event) == 4


def test_the_sweeper_expires_overdue_holds_and_their_pending_orders():
    event = make_event(capacity=10, max_per_user=4)
    user = make_user()
    overdue = services.create_hold(user=user, event_uuid=event.uuid, quantity=3)
    order = Order.objects.create(hold=overdue, amount_satang=event.price_satang)
    with freeze_time(timezone.now() + timedelta(minutes=4)):
        fresh = services.create_hold(user=make_user(username='later'), event_uuid=event.uuid, quantity=1)

    with freeze_time(timezone.now() + services.HOLD_TTL + timedelta(seconds=1)):
        expired = services.expire_holds()

    assert expired == 1
    assert Hold.objects.get(pk=overdue.pk).status == Hold.Status.EXPIRED
    assert Hold.objects.get(pk=fresh.pk).status == Hold.Status.ACTIVE
    assert Order.objects.get(pk=order.pk).status == Order.Status.EXPIRED
    assert _available(event) == 9


def test_the_sweeper_does_not_return_stock_for_a_released_hold():
    event = make_event(capacity=5)
    user = make_user()
    hold = services.create_hold(user=user, event_uuid=event.uuid, quantity=2)
    services.release_hold(user=user, hold_uuid=hold.uuid)

    with freeze_time(timezone.now() + services.HOLD_TTL + timedelta(seconds=1)):
        assert services.expire_holds() == 0

    assert _available(event) == 5


def test_the_sweeper_works_in_batches():
    event = make_event(capacity=10, max_per_user=1)
    for n in range(3):
        services.create_hold(user=make_user(username=f'buyer-{n}'), event_uuid=event.uuid, quantity=1)

    with freeze_time(timezone.now() + services.HOLD_TTL + timedelta(seconds=1)):
        assert services.expire_holds(batch_size=2) == 2
        assert services.expire_holds(batch_size=2) == 1

    assert _available(event) == 10
