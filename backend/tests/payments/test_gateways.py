import json
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from rest_framework.test import APIClient

from payments.gateways import check_configuration
from payments.gateways import get_gateway
from payments.gateways.base import ADAPTERS
from payments.gateways.base import WebhookNotice
from payments.gateways.base import register_gateway
from payments.gateways.mock import MockGateway
from payments.models import WebhookEvent


class FakeGateway:
    def create_charge(self, **kwargs):
        raise NotImplementedError

    def parse_webhook(self, *, body, headers):
        payload = json.loads(body)
        return WebhookNotice(event_id=payload['id'], event_type='charge.succeeded', payment_key='key', charge_id='chrg', payload=payload)


@pytest.fixture
def fake_registered():
    with mock.patch.dict(ADAPTERS, {'fake': FakeGateway}):
        yield


def _post(provider):
    with mock.patch('payments.tasks.process_succeeded.apply_async'):
        return APIClient().post(f'/api/webhooks/{provider}/', data=b'{"id": "evt_1"}', content_type='application/json')


def test_the_configured_gateway_is_the_registered_adapter():
    assert isinstance(get_gateway(), MockGateway)
    assert MockGateway.provider == 'mock'


def test_a_provider_cannot_be_registered_twice():
    with mock.patch.dict(ADAPTERS), pytest.raises(ImproperlyConfigured):
        register_gateway('mock')(FakeGateway)


@override_settings(PAYMENT_GATEWAY='omise')
def test_an_unregistered_gateway_is_refused_at_boot():
    with pytest.raises(ImproperlyConfigured, match='omise'):
        check_configuration()


@override_settings(PAYMENT_WEBHOOK_PROVIDERS=['mock', 'omise'])
def test_an_unregistered_webhook_provider_is_refused_at_boot():
    with pytest.raises(ImproperlyConfigured, match='omise'):
        check_configuration()


@pytest.mark.django_db
@pytest.mark.usefixtures('fake_registered')
def test_a_registered_provider_that_is_not_accepted_gets_no_webhooks():
    assert _post('fake').status_code == 404
    assert not WebhookEvent.objects.exists()


@pytest.mark.django_db
@pytest.mark.usefixtures('fake_registered')
@override_settings(PAYMENT_WEBHOOK_PROVIDERS=['mock', 'fake'])
def test_webhooks_from_the_previous_provider_are_accepted_while_switching():
    assert _post('fake').status_code == 200
    assert WebhookEvent.objects.get().provider == 'fake'
