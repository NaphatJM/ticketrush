from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound

from audit.models import ActivityLog
from mockgateway.exceptions import GatewayError
from mockgateway.models import FaultConfig
from mockgateway.models import MockCharge
from payments import services
from payments.exceptions import HoldExpiringSoon
from payments.exceptions import OrderNotPayable
from payments.exceptions import PaymentsUnavailable
from payments.models import Payment
from reliability.circuit import CircuitBreaker
from reliability.services import PENDING_LEASE
from tests.builders import make_event
from tests.builders import make_hold
from tests.builders import make_user
from ticketing.exceptions import HoldNotActive
from ticketing.models import Hold
from ticketing.models import Order


pytestmark = pytest.mark.django_db


def _checkout(hold):
    return services.submit_charge(services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))


def test_checkout_creates_an_order_and_a_charge_keyed_by_the_payment():
    hold = make_hold(event=make_event(price_satang=50_000), quantity=2)

    payment = _checkout(hold)

    assert payment.status == Payment.Status.PENDING
    assert (payment.order.status, payment.order.amount_satang) == (Order.Status.PENDING_PAYMENT, 100_000)
    charge = MockCharge.objects.get()
    assert charge.idempotency_key == str(payment.uuid)
    assert charge.expires_at == hold.expires_at
    assert payment.provider_charge_id == charge.charge_id
    assert payment.payment_url.endswith(f'/mock-gateway/charges/{charge.charge_id}/')
    assert ActivityLog.objects.filter(verb='order.created', target_id=str(payment.order.uuid)).exists()


def test_checking_out_again_resumes_the_same_order_and_charge():
    hold = make_hold()

    first = _checkout(hold)
    second = _checkout(hold)

    assert first.pk == second.pk
    assert Order.objects.count() == 1
    assert MockCharge.objects.count() == 1


def test_a_hold_about_to_expire_cannot_start_a_payment():
    hold = make_hold()
    Hold.objects.filter(pk=hold.pk).update(expires_at=timezone.now() + services.CHECKOUT_MIN_HOLD_LEFT - timedelta(seconds=1))

    with pytest.raises(HoldExpiringSoon):
        _checkout(hold)

    assert not Order.objects.exists()


def test_a_hold_past_its_expiry_is_refused_before_the_sweeper_runs():
    hold = make_hold()
    Hold.objects.filter(pk=hold.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

    with pytest.raises(HoldNotActive):
        _checkout(hold)


def test_another_users_hold_is_not_found():
    hold = make_hold()

    with pytest.raises(NotFound):
        services.prepare_checkout(user=make_user(username='intruder'), hold_uuid=hold.uuid)


def test_a_gateway_outage_keeps_the_order_so_a_retry_reuses_the_payment():
    hold = make_hold()
    FaultConfig.objects.update_or_create(pk=1, defaults={'error_rate': 1.0})

    with pytest.raises(PaymentsUnavailable):
        _checkout(hold)

    stranded = Payment.objects.get()
    assert stranded.status == Payment.Status.CREATED
    FaultConfig.objects.filter(pk=1).update(error_rate=0.0)

    payment = _checkout(hold)

    assert payment.pk == stranded.pk
    assert payment.status == Payment.Status.PENDING


def test_repeated_gateway_failures_open_the_circuit():
    hold = make_hold()

    with mock.patch('mockgateway.services.create_charge', side_effect=GatewayError) as create_charge:
        for _ in range(services.gateway_breaker.failure_threshold):
            with pytest.raises(PaymentsUnavailable):
                _checkout(hold)
        calls_before_open = create_charge.call_count

        with pytest.raises(PaymentsUnavailable):
            _checkout(hold)

    assert calls_before_open == services.gateway_breaker.failure_threshold * services.GATEWAY_ATTEMPTS
    assert create_charge.call_count == calls_before_open


def test_a_failed_payment_can_be_retried_with_a_new_payment():
    hold = make_hold()
    failed = _checkout(hold)
    Payment.objects.filter(pk=failed.pk).update(status=Payment.Status.FAILED)
    Order.objects.filter(pk=failed.order_id).update(status=Order.Status.FAILED)

    retry = _checkout(hold)

    assert retry.pk != failed.pk
    assert retry.order_id == failed.order_id
    assert Order.objects.get(pk=failed.order_id).status == Order.Status.PENDING_PAYMENT


def test_a_paid_order_cannot_be_checked_out_again():
    hold = make_hold()
    payment = _checkout(hold)
    Order.objects.filter(pk=payment.order_id).update(status=Order.Status.PAID)

    with pytest.raises(OrderNotPayable):
        _checkout(hold)


def test_the_gateway_timeouts_fit_inside_the_idempotency_lease():
    assert services.GATEWAY_TIMEOUT_SECONDS * services.GATEWAY_ATTEMPTS < PENDING_LEASE.total_seconds()


def test_an_unexpected_charge_error_is_raised_and_does_not_leave_the_circuit_stuck():
    hold = make_hold()
    breaker = CircuitBreaker(failure_threshold=1, reset_after_seconds=0)
    breaker.record_failure()

    with mock.patch.object(services, 'gateway_breaker', breaker):
        with mock.patch('payments.gateways.mock.MockGateway.create_charge', side_effect=RuntimeError('bug')), pytest.raises(RuntimeError):
            services.submit_charge(services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))
        payment = services.submit_charge(services.prepare_checkout(user=hold.user, hold_uuid=hold.uuid))

    assert payment.status == Payment.Status.PENDING
