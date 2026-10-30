from datetime import timedelta
from unittest import mock

import pytest
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from mockgateway import services as mock_gateway
from mockgateway.models import FaultConfig
from mockgateway.models import MockCharge
from payments import services
from payments.gateways.base import ChargeStatus
from payments.gateways.base import GatewayUnavailableError
from payments.models import Payment
from payments.models import Ticket
from payments.models import WebhookEvent
from reliability.circuit import CircuitBreaker
from reliability.models import OutboxMessage
from tests.builders import make_event
from tests.builders import make_hold
from tests.builders import make_user
from tests.concurrency import race
from ticketing import services as ticketing
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.models import Order


pytestmark = pytest.mark.django_db


def _checkout(hold) -> Payment:
    return services.submit_charge(services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))


def _settle(payment: Payment, status: str = MockCharge.Status.SUCCEEDED) -> MockCharge:
    """Settle the charge at the gateway without delivering its webhook."""
    charge = MockCharge.objects.get(idempotency_key=str(payment.uuid))
    charge.status = status
    charge.save(update_fields=['status'])
    return charge


def _age(payment: Payment, by: timedelta = timedelta(minutes=2)) -> None:
    Payment.objects.filter(pk=payment.pk).update(updated_on=timezone.now() - by)


def _reconcile(django_capture_on_commit_callbacks) -> dict[str, int]:
    with django_capture_on_commit_callbacks(execute=True):
        return services.reconcile_payments()


def _real_webhook(payment: Payment, event_id: str = 'evt_real') -> WebhookEvent:
    charge = MockCharge.objects.get(idempotency_key=str(payment.uuid))
    payload = mock_gateway.build_event(charge) | {'id': event_id}
    return WebhookEvent.objects.create(
        provider='mock', provider_event_id=event_id, event_type=payload['type'], payment_key=str(payment.uuid), payload=payload
    )


def test_a_lost_webhook_is_recovered_and_the_order_is_paid(django_capture_on_commit_callbacks):
    hold = make_hold(event=make_event(capacity=5), quantity=2)
    payment = _checkout(hold)
    _settle(payment)
    _age(payment)

    assert _reconcile(django_capture_on_commit_callbacks) == {'succeeded': 1}

    event = WebhookEvent.objects.get()
    assert (event.provider_event_id, event.event_type, event.payment_key) == (f'reconcile:{payment.uuid}', 'charge.succeeded', str(payment.uuid))
    assert event.processed_at is not None
    assert Payment.objects.get(pk=payment.pk).status == Payment.Status.SUCCEEDED
    assert Order.objects.get(pk=payment.order_id).status == Order.Status.PAID
    assert Hold.objects.get(pk=hold.pk).status == Hold.Status.CONVERTED
    assert Ticket.objects.filter(order_id=payment.order_id).count() == 2


def test_a_recovered_payment_whose_hold_expired_takes_its_stock_back(django_capture_on_commit_callbacks):
    event = make_event(capacity=5)
    hold = make_hold(event=event, quantity=2)
    payment = _checkout(hold)
    _settle(payment)
    Hold.objects.filter(pk=hold.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    ticketing.expire_holds()
    assert Event.objects.get(pk=event.pk).available == 5
    _age(payment)

    _reconcile(django_capture_on_commit_callbacks)

    assert Order.objects.get(pk=payment.order_id).status == Order.Status.PAID
    assert Hold.objects.get(pk=hold.pk).status == Hold.Status.CONVERTED
    assert Event.objects.get(pk=event.pk).available == 3
    assert Ticket.objects.filter(order_id=payment.order_id).count() == 2


def test_a_failed_charge_is_recorded_as_failed(django_capture_on_commit_callbacks):
    payment = _checkout(make_hold())
    _settle(payment, MockCharge.Status.FAILED)
    _age(payment)

    assert _reconcile(django_capture_on_commit_callbacks) == {'failed': 1}

    assert Payment.objects.get(pk=payment.pk).status == Payment.Status.FAILED
    assert Order.objects.get(pk=payment.order_id).status == Order.Status.FAILED


def test_a_real_webhook_arriving_after_reconcile_is_a_duplicate(django_capture_on_commit_callbacks):
    payment = _checkout(make_hold(quantity=2))
    _settle(payment)
    _age(payment)
    _reconcile(django_capture_on_commit_callbacks)

    assert services.apply_charge_succeeded(webhook_event_id=_real_webhook(payment).pk) == 'duplicate'

    assert Ticket.objects.filter(order_id=payment.order_id).count() == 2


def test_a_payment_already_paid_by_its_webhook_is_not_asked_about(django_capture_on_commit_callbacks):
    payment = _checkout(make_hold())
    _settle(payment)
    services.apply_charge_succeeded(webhook_event_id=_real_webhook(payment).pk)
    _age(payment)

    with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge') as retrieve:
        assert _reconcile(django_capture_on_commit_callbacks) == {}

    retrieve.assert_not_called()


def test_an_unprocessed_reconcile_event_is_stored_once_across_runs():
    payment = _checkout(make_hold())
    _settle(payment)
    _age(payment)

    services.reconcile_payments()
    Payment.objects.filter(pk=payment.pk).update(reconciled_at=None)
    assert services.reconcile_payments() == {'duplicate': 1}

    assert WebhookEvent.objects.count() == 1
    assert OutboxMessage.objects.filter(topic='payments.process_succeeded').count() == 1


def test_a_gateway_outage_changes_nothing(django_capture_on_commit_callbacks):
    payment = _checkout(make_hold())
    _settle(payment)
    _age(payment)
    FaultConfig.objects.update_or_create(pk=1, defaults={'error_rate': 1.0})

    assert _reconcile(django_capture_on_commit_callbacks) == {'unavailable': 1}

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    assert payment.reconciled_at is None
    assert Order.objects.get(pk=payment.order_id).status == Order.Status.PENDING_PAYMENT
    assert not WebhookEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_an_open_circuit_skips_the_gateway():
    payment = _checkout(make_hold())
    _age(payment)
    for _ in range(services.gateway_breaker.failure_threshold):
        services.gateway_breaker.record_failure()

    with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge') as retrieve:
        assert services.reconcile_payments() == {'circuit_open': 1}

    retrieve.assert_not_called()


def test_repeated_gateway_failures_open_the_circuit():
    for _ in range(services.gateway_breaker.failure_threshold):
        _age(_checkout(make_hold()))

    with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge', side_effect=GatewayUnavailableError('down')):
        services.reconcile_payments()

    assert services.gateway_breaker.state == 'open'


def test_an_unexpected_lookup_error_is_raised_and_does_not_leave_the_circuit_stuck():
    _age(_checkout(make_hold()))
    breaker = CircuitBreaker(failure_threshold=1, reset_after_seconds=0)
    breaker.record_failure()

    with mock.patch.object(services, 'gateway_breaker', breaker):
        with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge', side_effect=RuntimeError('bug')), pytest.raises(RuntimeError):
            services.reconcile_payments()
        with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge', return_value=ChargeStatus.PENDING) as retrieve:
            assert services.reconcile_payments() == {'pending': 1}

    retrieve.assert_called_once()


def test_lookups_use_a_short_timeout_and_a_run_ends_before_the_next_one_starts():
    _age(_checkout(make_hold()))
    interval = settings.CELERY_BEAT_SCHEDULE['reconcile-payments']['schedule']

    with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge', return_value=ChargeStatus.PENDING) as retrieve:
        services.reconcile_payments()

    assert retrieve.call_args.kwargs['timeout'] == services.RECONCILE_LOOKUP_TIMEOUT_SECONDS
    assert services.RECONCILE_LOOKUP_TIMEOUT_SECONDS < services.GATEWAY_TIMEOUT_SECONDS
    assert services.RECONCILE_RUN_BUDGET_SECONDS + services.RECONCILE_LOOKUP_TIMEOUT_SECONDS < interval / 2


def test_a_created_payment_whose_charge_exists_at_the_gateway_is_paid(django_capture_on_commit_callbacks):
    hold = make_hold()
    payment = services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid)
    # The charge was created, but the checkout timed out before it saved the charge.
    mock_gateway.create_charge(idempotency_key=str(payment.uuid), amount_satang=payment.amount_satang, expires_at=payment.expires_at, timeout=5)
    _settle(payment)
    _age(payment)

    _reconcile(django_capture_on_commit_callbacks)

    assert Payment.objects.get(pk=payment.pk).status == Payment.Status.SUCCEEDED
    assert Order.objects.get(pk=payment.order_id).status == Order.Status.PAID


@pytest.mark.parametrize('created_charge', [False, True], ids=['no-charge', 'unpaid-charge'])
def test_an_unsettled_payment_is_left_alone(created_charge, django_capture_on_commit_callbacks):
    hold = make_hold()
    payment = _checkout(hold) if created_charge else services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid)
    _age(payment)

    assert _reconcile(django_capture_on_commit_callbacks) == {'pending' if created_charge else 'not_found': 1}

    payment.refresh_from_db()
    assert payment.status == (Payment.Status.PENDING if created_charge else Payment.Status.CREATED)
    assert payment.reconciled_at is not None
    assert not WebhookEvent.objects.exists()


def test_a_charge_past_its_expiry_that_was_never_paid_is_failed(django_capture_on_commit_callbacks):
    payment = _checkout(make_hold())
    MockCharge.objects.filter(idempotency_key=str(payment.uuid)).update(expires_at=timezone.now() - timedelta(minutes=1))
    _age(payment)

    assert _reconcile(django_capture_on_commit_callbacks) == {'failed': 1}


def test_recent_recently_checked_and_long_expired_payments_are_skipped():
    _checkout(make_hold())
    checked = _checkout(make_hold())
    _age(checked)
    Payment.objects.filter(pk=checked.pk).update(reconciled_at=timezone.now())
    stale = _checkout(make_hold())
    Payment.objects.filter(pk=stale.pk).update(expires_at=timezone.now() - services.RECONCILE_HORIZON - timedelta(minutes=1))
    _age(stale)

    with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge') as retrieve:
        assert services.reconcile_payments() == {}

    retrieve.assert_not_called()


def test_a_batch_asks_about_pending_payments_before_created_ones_and_oldest_expiry_first():
    created = services.prepare_checkout(user=(hold := make_hold()).user, hold_uuid=hold.uuid)
    later = _checkout(make_hold())
    sooner = _checkout(make_hold())
    Payment.objects.filter(pk=created.pk).update(expires_at=timezone.now())
    Payment.objects.filter(pk=sooner.pk).update(expires_at=timezone.now() + timedelta(seconds=30))
    for payment in (created, later, sooner):
        _age(payment)

    with mock.patch('payments.gateways.mock.MockGateway.retrieve_charge', return_value=ChargeStatus.PENDING) as retrieve:
        services.reconcile_payments(batch_size=2)

    assert [call.kwargs['idempotency_key'] for call in retrieve.call_args_list] == [str(sooner.uuid), str(later.uuid)]


@pytest.mark.django_db(transaction=True)
def test_reconcile_and_a_real_webhook_racing_issue_one_set_of_tickets():
    event = make_event(capacity=5, max_per_user=3)
    hold = make_hold(event=event, quantity=3)
    payment = _checkout(hold)
    _settle(payment)
    _age(payment)
    with mock.patch('reliability.outbox.publish_pending'):
        services.reconcile_payments()
    reconciled = WebhookEvent.objects.get(provider_event_id=f'reconcile:{payment.uuid}')
    real = _real_webhook(payment)

    results = race([lambda pk=pk: services.apply_charge_succeeded(webhook_event_id=pk) for pk in (reconciled.pk, real.pk)])

    assert sorted(results) == ['duplicate', 'paid']
    assert Ticket.objects.filter(order_id=payment.order_id).count() == 3
    assert Event.objects.get(pk=event.pk).available == 2
    assert Hold.objects.filter(event=event).aggregate(total=Sum('quantity'))['total'] == 3


def test_staff_can_list_paid_orders_left_unfulfilled(client):
    client.force_login(make_user(username='ops', is_staff=True, is_superuser=True))
    unfulfilled = Order.objects.create(hold=make_hold(), amount_satang=1, status=Order.Status.PAID_UNFULFILLED)
    Order.objects.create(hold=make_hold(), amount_satang=1, status=Order.Status.PAID)

    response = client.get('/admin/ticketing/order/', {'status__exact': Order.Status.PAID_UNFULFILLED})

    assert response.status_code == 200
    assert [order.pk for order in response.context['cl'].result_list] == [unfulfilled.pk]
