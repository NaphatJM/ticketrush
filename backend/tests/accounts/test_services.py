from datetime import timedelta
from unittest import mock

import pytest
from django.db import IntegrityError
from django.utils import timezone
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import services
from accounts.models import User
from accounts.tasks import flush_expired_tokens
from tests.builders import make_user
from utils.drf_helper.throttling import FailClosedThrottle
from utils.drf_helper.throttling import ThrottleStoreUnavailable


pytestmark = pytest.mark.django_db


def test_an_unrelated_integrity_error_is_not_reported_as_a_taken_username():
    with mock.patch.object(services, 'log_action', side_effect=IntegrityError('other constraint')), pytest.raises(IntegrityError):
        services.register_user(username='alice', email='alice@example.com', password='correct-horse-battery-7')

    assert not User.objects.filter(username='alice').exists()


def test_a_throttle_without_its_own_outage_error_still_answers_503():
    class BareThrottle(FailClosedThrottle):
        rate = '1/min'

        def get_cache_key(self, request, view):
            return 'bare'

    broken_cache = mock.Mock(get=mock.Mock(side_effect=RedisConnectionError('down')))

    with mock.patch.object(FailClosedThrottle, 'cache', broken_cache), pytest.raises(ThrottleStoreUnavailable):
        BareThrottle().allow_request(mock.Mock(), None)


def test_expired_refresh_tokens_are_flushed_and_live_ones_kept():
    user = make_user()
    RefreshToken.for_user(user)
    expired = RefreshToken.for_user(user)
    OutstandingToken.objects.filter(jti=expired['jti']).update(expires_at=timezone.now() - timedelta(seconds=1))

    assert flush_expired_tokens() == 1
    assert OutstandingToken.objects.count() == 1


def test_the_admin_never_shows_a_stored_refresh_token():
    staff = make_user(username='staff', is_staff=True, is_superuser=True)
    refresh = str(RefreshToken.for_user(staff))
    token = OutstandingToken.objects.get()
    client = APIClient()
    client.force_login(staff)

    listing = client.get('/admin/token_blacklist/outstandingtoken/')
    detail = client.get(f'/admin/token_blacklist/outstandingtoken/{token.pk}/change/')

    assert listing.status_code == detail.status_code == 200
    assert refresh not in listing.content.decode()
    assert refresh not in detail.content.decode()
