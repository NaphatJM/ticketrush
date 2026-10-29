import logging
from collections.abc import Mapping
from datetime import timedelta

from django.db import IntegrityError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import NotFound

from audit.constants import ActivityVerb
from audit.services import log_action
from reliability import outbox
from reliability.circuit import CircuitBreaker
from ticketing.exceptions import HoldNotActive
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.models import Order

from .exceptions import HoldExpiringSoon
from .exceptions import InvalidWebhookSignature
from .exceptions import OrderNotPayable
from .exceptions import PaymentsUnavailable
from .gateways import get_gateway
from .gateways import get_webhook_gateway
from .gateways.base import CHARGE_FAILED
from .gateways.base import CHARGE_SUCCEEDED
from .gateways.base import Charge
from .gateways.base import GatewayUnavailableError
from .gateways.base import InvalidWebhookError
from .models import Payment
from .models import Ticket
from .models import WebhookEvent
from .ticket_codes import sign_ticket


logger = logging.getLogger(__name__)

CHECKOUT_MIN_HOLD_LEFT = timedelta(seconds=60)
# Attempts x timeout must stay below reliability.services.PENDING_LEASE, or a duplicate checkout could take over a live request.
GATEWAY_TIMEOUT_SECONDS = 5.0
GATEWAY_ATTEMPTS = 2

gateway_breaker = CircuitBreaker(failure_threshold=5, reset_after_seconds=30)

_TOPICS = {CHARGE_SUCCEEDED: 'payments.process_succeeded', CHARGE_FAILED: 'payments.process_failed'}
_OPEN_PAYMENT = (Payment.Status.CREATED, Payment.Status.PENDING)


def prepare_checkout(*, user, hold_uuid) -> Payment:
    """Commit the order and a payment to charge. A repeat for the same hold resumes them instead of creating new ones."""
    now = timezone.now()
    gateway = get_gateway()
    with transaction.atomic():
        # Locks the hold only, not the event: release_hold also locks the hold first, so it cannot slip in an early release.
        hold = Hold.objects.select_for_update(of=('self',)).select_related('event').filter(uuid=hold_uuid, user=user).first()
        if hold is None:
            raise NotFound
        if hold.status != Hold.Status.ACTIVE or hold.expires_at <= now:
            raise HoldNotActive
        if hold.expires_at - now < CHECKOUT_MIN_HOLD_LEFT:
            raise HoldExpiringSoon

        order = Order.objects.filter(hold=hold).first()
        if order is None:
            order = Order.objects.create(hold=hold, amount_satang=hold.event.price_satang * hold.quantity)
            log_action(ActivityVerb.ORDER_CREATED, actor=user, target=order, detail={'hold': str(hold.uuid), 'amount_satang': order.amount_satang})
        elif order.status == Order.Status.FAILED:
            Order.objects.filter(pk=order.pk, status=Order.Status.FAILED).update(status=Order.Status.PENDING_PAYMENT, updated_on=now)
        elif order.status != Order.Status.PENDING_PAYMENT:
            raise OrderNotPayable

        payment = order.payments.filter(status__in=_OPEN_PAYMENT).order_by('-id').first()
        if payment is None:
            payment = Payment.objects.create(order=order, provider=gateway.provider, amount_satang=order.amount_satang, expires_at=hold.expires_at)
    return payment


def submit_charge(payment: Payment) -> Payment:
    """Create the gateway charge for a committed payment. Runs outside any transaction so no row lock waits on the network."""
    if payment.status == Payment.Status.CREATED:
        charge = _create_charge(payment)
        Payment.objects.filter(pk=payment.pk, status=Payment.Status.CREATED).update(
            status=Payment.Status.PENDING, provider_charge_id=charge.charge_id, payment_url=charge.payment_url, updated_on=timezone.now()
        )
        payment.refresh_from_db()
    return payment


def _create_charge(payment: Payment) -> Charge:
    if not gateway_breaker.allow():
        raise PaymentsUnavailable
    gateway = get_gateway()
    for attempt in range(1, GATEWAY_ATTEMPTS + 1):
        try:
            charge = gateway.create_charge(
                idempotency_key=str(payment.uuid), amount_satang=payment.amount_satang, expires_at=payment.expires_at, timeout=GATEWAY_TIMEOUT_SECONDS
            )
        except GatewayUnavailableError as exc:
            logger.warning('gateway charge failed', extra={'attempt': attempt, 'provider': gateway.provider}, exc_info=exc)
            continue
        gateway_breaker.record_success()
        return charge
    gateway_breaker.record_failure()
    raise PaymentsUnavailable


def receive_webhook(*, provider: str, body: bytes, headers: Mapping[str, str]) -> bool:
    """Store a verified event once and queue its processing; returns False for a duplicate delivery."""
    gateway = get_webhook_gateway(provider)
    if gateway is None:
        raise NotFound
    try:
        notice = gateway.parse_webhook(body=body, headers=headers)
    except InvalidWebhookError as exc:
        logger.warning('webhook rejected', extra={'provider': provider, 'reason': str(exc)})
        raise InvalidWebhookSignature from exc

    with transaction.atomic():
        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(
                    provider=provider,
                    provider_event_id=notice.event_id,
                    event_type=notice.event_type,
                    payment_key=notice.payment_key,
                    payload=notice.payload,
                )
        except IntegrityError:
            logger.info('duplicate webhook ignored', extra={'provider': provider, 'webhook_event_id': notice.event_id})
            return False
        topic = _TOPICS.get(notice.event_type)
        if topic is not None:
            outbox.enqueue(topic, {'webhook_event_id': event.pk})
    return True


def apply_charge_succeeded(*, webhook_event_id: int) -> str:
    now = timezone.now()
    with transaction.atomic():
        claimed = _claim_event(webhook_event_id)
        if claimed is None:
            return 'duplicate'
        event, payment, hold = claimed
        order = payment.order

        Payment.objects.filter(pk=payment.pk, status__in=_OPEN_PAYMENT).update(status=Payment.Status.SUCCEEDED, updated_on=now)
        paid = Order.objects.filter(pk=order.pk, status__in=(Order.Status.PENDING_PAYMENT, Order.Status.FAILED, Order.Status.EXPIRED)).update(
            status=Order.Status.PAID, paid_at=now, updated_on=now
        )
        if not paid:
            _mark_processed(event, now)
            return 'duplicate'

        converted = Hold.objects.filter(pk=hold.pk, status=Hold.Status.ACTIVE).update(status=Hold.Status.CONVERTED, updated_on=now)
        if not converted:
            # The hold expired and returned its stock before the payment landed; take the stock again, ignoring the sale window.
            retaken = Event.objects.filter(pk=hold.event_id, available__gte=hold.quantity).update(
                available=F('available') - hold.quantity, updated_on=now
            )
            if not retaken:
                Order.objects.filter(pk=order.pk, status=Order.Status.PAID).update(status=Order.Status.PAID_UNFULFILLED, updated_on=now)
                log_action(ActivityVerb.ORDER_PAID_UNFULFILLED, target=order, detail={'quantity': hold.quantity})
                _mark_processed(event, now)
                logger.error('paid order left unfulfilled', extra={'order_id': str(order.uuid), 'event_id': str(hold.event.uuid)})
                return 'unfulfilled'
            Hold.objects.filter(pk=hold.pk, status=Hold.Status.EXPIRED).update(status=Hold.Status.CONVERTED, updated_on=now)

        tickets = [Ticket(order=order, seq=seq) for seq in range(1, hold.quantity + 1)]
        for ticket in tickets:
            ticket.code = sign_ticket(ticket.uuid)
        Ticket.objects.bulk_create(tickets)
        log_action(ActivityVerb.ORDER_PAID, target=order, detail={'tickets': len(tickets), 'late': not converted})
        _mark_processed(event, now)
    logger.info('order paid', extra={'order_id': str(order.uuid), 'tickets': len(tickets)})
    return 'paid'


def apply_charge_failed(*, webhook_event_id: int) -> str:
    now = timezone.now()
    with transaction.atomic():
        claimed = _claim_event(webhook_event_id)
        if claimed is None:
            return 'duplicate'
        event, payment, _hold = claimed
        failed = Payment.objects.filter(pk=payment.pk, status__in=_OPEN_PAYMENT).update(status=Payment.Status.FAILED, updated_on=now)
        if failed:
            # The hold stays active, so the buyer can check out again until it expires.
            Order.objects.filter(pk=payment.order_id, status=Order.Status.PENDING_PAYMENT).update(status=Order.Status.FAILED, updated_on=now)
            log_action(ActivityVerb.ORDER_PAYMENT_FAILED, target=payment.order, detail={'payment': str(payment.uuid)})
        _mark_processed(event, now)
    return 'failed' if failed else 'duplicate'


def _claim_event(webhook_event_id: int) -> tuple[WebhookEvent, Payment, Hold] | None:
    """Lock the event, then the hold, which checkout and the sweeper also lock before anything they change."""
    event = WebhookEvent.objects.select_for_update().get(pk=webhook_event_id)
    if event.processed_at is not None:
        return None
    payment = Payment.objects.select_related('order').get(uuid=event.payment_key, provider=event.provider)
    hold = Hold.objects.select_for_update(of=('self',)).select_related('event').get(pk=payment.order.hold_id)
    return event, payment, hold


def _mark_processed(event: WebhookEvent, now) -> None:
    event.processed_at = now
    event.save(update_fields=['processed_at'])
