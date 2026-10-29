import json
from collections.abc import Mapping
from datetime import datetime

from django.conf import settings

from mockgateway import services as mock_gateway
from mockgateway import signing
from mockgateway.exceptions import GatewayError

from .base import Charge
from .base import GatewayUnavailableError
from .base import InvalidWebhookError
from .base import WebhookNotice
from .base import register_gateway


@register_gateway('mock')
class MockGateway:
    def create_charge(self, *, idempotency_key: str, amount_satang: int, expires_at: datetime, timeout: float) -> Charge:
        try:
            charge = mock_gateway.create_charge(idempotency_key=idempotency_key, amount_satang=amount_satang, expires_at=expires_at, timeout=timeout)
        except GatewayError as exc:
            raise GatewayUnavailableError(str(exc)) from exc
        return Charge(charge_id=charge.charge_id, payment_url=mock_gateway.payment_url(charge))

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> WebhookNotice:
        try:
            signing.verify(body, headers.get(signing.SIGNATURE_HEADER), secret=settings.MOCK_GATEWAY_WEBHOOK_SECRET)
        except signing.InvalidSignatureError as exc:
            raise InvalidWebhookError(str(exc)) from exc
        try:
            payload = json.loads(body)
            data = payload['data']
            return WebhookNotice(
                event_id=str(payload['id']),
                event_type=str(payload['type']),
                payment_key=str(data['idempotency_key']),
                charge_id=str(data['charge_id']),
                payload=payload,
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidWebhookError('malformed event body') from exc
