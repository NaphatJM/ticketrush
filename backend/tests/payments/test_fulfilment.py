from datetime import timedelta

import pytest
from django.core.signing import BadSignature
from django.utils import timezone

from audit.models import ActivityLog
from mockgateway import services as mock_gateway
from mockgateway.models import MockCharge
from payments import services
from payments.models import Payment
from payments.models import Ticket
from payments.models import WebhookEvent
from payments.ticket_codes import verify_ticket_code
from tests.builders import make_event
from tests.builders import make_hold
from ticketing import services as ticketing
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.models import Order


pytestmark = pytest.mark.django_db


def _paid_checkout(hold) -> Payment:
    return services.submit_charge(services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))


def _webhook(payment: Payment, *, succeeded: bool = True, event_id: str = 'evt_1') -> WebhookEvent:
    charge = MockCharge.objects.get(charge_id=payment.provider_charge_id)
    charge.status = MockCharge.Status.SUCCEEDED if succeeded else MockCharge.Status.FAILED
    payload = mock_gateway.build_event(charge) | {'id': event_id}
    return WebhookEvent.objects.create(
        provider='mock', provider_event_id=event_id, event_type=payload['type'], payment_key=str(payment.uuid), payload=payload
    )


def _expire(hold):
    Hold.objects.filter(pk=hold.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    ticketing.expire_holds()


def test_a_succeeded_charge_pays_the_order_converts_the_hold_and_issues_tickets():
    hold = make_hold(event=make_event(max_per_user=3), quantity=3)
    payment = _paid_checkout(hold)
    event = _webhook(payment)

    assert services.apply_charge_succeeded(webhook_event_id=event.pk) == 'paid'

    order = Order.objects.get(pk=payment.order_id)
    assert order.status == Order.Status.PAID
    assert order.paid_at is not None
    assert Hold.objects.get(pk=hold.pk).status == Hold.Status.CONVERTED
    assert Payment.objects.get(pk=payment.pk).status == Payment.Status.SUCCEEDED
    tickets = list(Ticket.objects.filter(order=order))
    assert [ticket.seq for ticket in tickets] == [1, 2, 3]
    assert all(verify_ticket_code(ticket.code) == ticket.uuid for ticket in tickets)
    assert WebhookEvent.objects.get(pk=event.pk).processed_at is not None
    assert ActivityLog.objects.filter(verb='order.paid').count() == 1


def test_processing_the_same_event_twice_issues_tickets_once():
    payment = _paid_checkout(make_hold())
    event = _webhook(payment)
    services.apply_charge_succeeded(webhook_event_id=event.pk)

    assert services.apply_charge_succeeded(webhook_event_id=event.pk) == 'duplicate'

    assert Ticket.objects.count() == 1


def test_a_second_success_event_for_a_paid_order_issues_nothing():
    payment = _paid_checkout(make_hold())
    services.apply_charge_succeeded(webhook_event_id=_webhook(payment, event_id='evt_1').pk)

    assert services.apply_charge_succeeded(webhook_event_id=_webhook(payment, event_id='evt_2').pk) == 'duplicate'

    assert Ticket.objects.count() == 1


def test_a_late_payment_takes_the_stock_again_when_some_is_left():
    event = make_event(capacity=5)
    hold = make_hold(event=event, quantity=2)
    payment = _paid_checkout(hold)
    _expire(hold)
    assert Event.objects.get(pk=event.pk).available == 5

    assert services.apply_charge_succeeded(webhook_event_id=_webhook(payment).pk) == 'paid'

    assert Event.objects.get(pk=event.pk).available == 3
    assert Hold.objects.get(pk=hold.pk).status == Hold.Status.CONVERTED
    assert Ticket.objects.count() == 2


def test_a_late_payment_with_no_stock_left_is_marked_unfulfilled():
    event = make_event(capacity=1, max_per_user=1)
    hold = make_hold(event=event)
    payment = _paid_checkout(hold)
    _expire(hold)
    make_hold(event=event)

    assert services.apply_charge_succeeded(webhook_event_id=_webhook(payment).pk) == 'unfulfilled'

    assert Order.objects.get(pk=payment.order_id).status == Order.Status.PAID_UNFULFILLED
    assert Event.objects.get(pk=event.pk).available == 0
    assert not Ticket.objects.exists()
    assert ActivityLog.objects.filter(verb='order.paid_unfulfilled').exists()


def test_a_failed_charge_fails_the_order_but_keeps_the_hold():
    hold = make_hold()
    payment = _paid_checkout(hold)

    assert services.apply_charge_failed(webhook_event_id=_webhook(payment, succeeded=False).pk) == 'failed'

    assert Order.objects.get(pk=payment.order_id).status == Order.Status.FAILED
    assert Payment.objects.get(pk=payment.pk).status == Payment.Status.FAILED
    assert Hold.objects.get(pk=hold.pk).status == Hold.Status.ACTIVE


def test_an_altered_ticket_code_is_rejected():
    payment = _paid_checkout(make_hold())
    services.apply_charge_succeeded(webhook_event_id=_webhook(payment).pk)
    code = Ticket.objects.get().code

    with pytest.raises(BadSignature):
        verify_ticket_code(code[:-1] + ('A' if code[-1] != 'A' else 'B'))
