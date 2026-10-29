import logging
import random
import secrets
import time
from datetime import datetime

from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from .exceptions import ChargeExpired
from .exceptions import ChargeNotPending
from .exceptions import GatewayError
from .exceptions import GatewayTimeoutError
from .models import FaultConfig
from .models import MockCharge
from .tasks import deliver_webhook


logger = logging.getLogger(__name__)


def create_charge(*, idempotency_key: str, amount_satang: int, expires_at: datetime, timeout: float) -> MockCharge:
    """Return the charge for this key, creating it on first use, the way a provider honours an idempotency key."""
    config = FaultConfig.load()
    delay = config.latency_ms / 1000
    if delay > timeout:
        time.sleep(timeout)
        raise GatewayTimeoutError(f'no response within {timeout} s')
    time.sleep(delay)
    if random.random() < config.error_rate:  # noqa: S311
        raise GatewayError('injected charge error')

    try:
        with transaction.atomic():
            charge, _ = MockCharge.objects.get_or_create(
                idempotency_key=idempotency_key, defaults={'amount_satang': amount_satang, 'expires_at': expires_at}
            )
    except IntegrityError:
        charge = MockCharge.objects.get(idempotency_key=idempotency_key)
    if charge.amount_satang != amount_satang:
        raise GatewayError('idempotency key reused with a different amount')
    return charge


def payment_url(charge: MockCharge) -> str:
    return f'{settings.PUBLIC_API_URL}/mock-gateway/charges/{charge.charge_id}/'


def get_charge(charge_id: str) -> MockCharge:
    charge = MockCharge.objects.filter(charge_id=charge_id).first()
    if charge is None:
        raise NotFound
    return charge


def pay(*, charge_id: str, succeed: bool) -> MockCharge:
    """Settle a pending charge and send its webhook. A charge past its expiry fails instead."""
    now = timezone.now()
    with transaction.atomic():
        charge = MockCharge.objects.select_for_update().filter(charge_id=charge_id).first()
        if charge is None:
            raise NotFound
        if charge.status != MockCharge.Status.PENDING:
            raise ChargeNotPending
        expired = charge.expires_at <= now
        if expired:
            charge.status = MockCharge.Status.EXPIRED
        else:
            charge.status = MockCharge.Status.SUCCEEDED if succeed else MockCharge.Status.FAILED
        charge.save(update_fields=['status'])
        event = build_event(charge)
        transaction.on_commit(lambda: deliver_webhook.delay(event=event))
    logger.info('mock charge settled', extra={'charge_id': charge.charge_id, 'status': charge.status})
    if expired:
        raise ChargeExpired
    return charge


def build_event(charge: MockCharge) -> dict:
    event_type = 'charge.succeeded' if charge.status == MockCharge.Status.SUCCEEDED else 'charge.failed'
    return {
        'id': f'evt_mock_{secrets.token_hex(12)}',
        'type': event_type,
        'created': int(time.time()),
        'data': {
            'charge_id': charge.charge_id,
            'idempotency_key': charge.idempotency_key,
            'amount_satang': charge.amount_satang,
            'status': charge.status,
        },
    }
