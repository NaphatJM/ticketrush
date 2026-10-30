from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from typing import Protocol

from django.core.exceptions import ImproperlyConfigured


CHARGE_SUCCEEDED = 'charge.succeeded'
CHARGE_FAILED = 'charge.failed'


class ChargeStatus(StrEnum):
    SUCCEEDED = 'succeeded'
    #: Declined, cancelled, or expired; the charge can no longer succeed.
    FAILED = 'failed'
    PENDING = 'pending'
    NOT_FOUND = 'not_found'


class GatewayUnavailableError(Exception):
    """The call failed or timed out; retrying with the same idempotency key cannot create a second charge."""


class InvalidWebhookError(Exception):
    pass


@dataclass(frozen=True)
class Charge:
    charge_id: str
    payment_url: str


@dataclass(frozen=True)
class WebhookNotice:
    event_id: str
    event_type: str
    #: The idempotency key sent with the charge, which is the payment's UUID.
    payment_key: str
    charge_id: str
    payload: dict[str, Any]


class GatewayAdapter(Protocol):
    provider: str

    def create_charge(self, *, idempotency_key: str, amount_satang: int, expires_at: datetime, timeout: float) -> Charge: ...

    def retrieve_charge(self, *, idempotency_key: str, timeout: float) -> ChargeStatus: ...

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> WebhookNotice: ...


ADAPTERS: dict[str, type[GatewayAdapter]] = {}


def register_gateway(provider: str):
    """Class decorator that makes an adapter selectable as `DJANGO_PAYMENT_GATEWAY=<provider>`."""

    def decorator(cls: type[GatewayAdapter]) -> type[GatewayAdapter]:
        if provider in ADAPTERS:
            raise ImproperlyConfigured(f'payment gateway {provider!r} is registered twice')
        cls.provider = provider
        ADAPTERS[provider] = cls
        return cls

    return decorator
