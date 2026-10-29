from unittest import mock

import pytest
from django.test import RequestFactory
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.throttles import AuthIPThrottle
from audit.middleware import resolve_client_ip
from tests.builders import make_user


SECRET = 'bff-secret-for-tests-0123456789abcdef'


def _request(**headers):
    return RequestFactory().get('/', REMOTE_ADDR='10.0.0.1', **headers)


@override_settings(BFF_SHARED_SECRET=SECRET)
def test_the_bff_client_ip_is_used_when_the_secret_matches():
    assert resolve_client_ip(_request(HTTP_BFF_SECRET=SECRET, HTTP_BFF_CLIENT_IP='203.0.113.7')) == '203.0.113.7'


@override_settings(BFF_SHARED_SECRET=SECRET)
@pytest.mark.parametrize('sent', ['', 'wrong', SECRET[:-1]])
def test_the_bff_client_ip_is_ignored_without_the_right_secret(sent):
    assert resolve_client_ip(_request(HTTP_BFF_SECRET=sent, HTTP_BFF_CLIENT_IP='203.0.113.7')) == '10.0.0.1'


@override_settings(BFF_SHARED_SECRET='')
def test_the_bff_header_is_ignored_when_no_secret_is_configured():
    assert resolve_client_ip(_request(HTTP_BFF_SECRET='', HTTP_BFF_CLIENT_IP='203.0.113.7')) == '10.0.0.1'


@override_settings(BFF_SHARED_SECRET=SECRET)
def test_a_malformed_bff_client_ip_falls_back_to_the_caller():
    assert resolve_client_ip(_request(HTTP_BFF_SECRET=SECRET, HTTP_BFF_CLIENT_IP='203.0.113.7, 10.0.0.2')) == '10.0.0.1'


@override_settings(BFF_SHARED_SECRET=SECRET, TRUST_FORWARDED_FOR=True)
def test_the_bff_client_ip_wins_over_x_forwarded_for():
    request = _request(HTTP_BFF_SECRET=SECRET, HTTP_BFF_CLIENT_IP='2001:db8::1', HTTP_X_FORWARDED_FOR='198.51.100.1')

    assert resolve_client_ip(request) == '2001:db8::1'


@pytest.mark.django_db
@override_settings(BFF_SHARED_SECRET=SECRET)
def test_users_behind_one_bff_get_separate_ip_throttle_buckets():
    make_user()
    rates = {**AuthIPThrottle.THROTTLE_RATES, 'auth_ip': '1/min'}

    def login(client_ip):
        headers = {'BFF-Secret': SECRET, 'BFF-Client-IP': client_ip}
        return APIClient(REMOTE_ADDR='10.0.0.1').post('/api/auth/login/', {'username': 'buyer', 'password': 'wrong'}, format='json', headers=headers)

    with mock.patch.object(AuthIPThrottle, 'THROTTLE_RATES', rates):
        statuses = [login('203.0.113.1').status_code, login('203.0.113.1').status_code, login('203.0.113.2').status_code]

    assert statuses == [401, 429, 401]
