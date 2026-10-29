from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from . import mock  # noqa: F401 -- importing an adapter module registers it
from .base import ADAPTERS
from .base import GatewayAdapter


def get_gateway() -> GatewayAdapter:
    return ADAPTERS[settings.PAYMENT_GATEWAY]()


def get_webhook_gateway(provider: str) -> GatewayAdapter | None:
    """The adapter for an incoming webhook, or None unless `provider` is accepted by DJANGO_PAYMENT_WEBHOOK_PROVIDERS."""
    if provider not in webhook_providers():
        return None
    return ADAPTERS[provider]()


def webhook_providers() -> list[str]:
    return settings.PAYMENT_WEBHOOK_PROVIDERS or [settings.PAYMENT_GATEWAY]


def check_configuration() -> None:
    unknown = sorted({settings.PAYMENT_GATEWAY, *webhook_providers()} - ADAPTERS.keys())
    if unknown:
        raise ImproperlyConfigured(f'no payment gateway adapter is registered for {unknown}; registered: {sorted(ADAPTERS)}')
