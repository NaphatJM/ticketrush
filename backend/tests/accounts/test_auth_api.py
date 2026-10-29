from unittest import mock

import jwt
import pytest
from django.conf import settings
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from accounts.models import User
from accounts.throttles import AuthIPThrottle
from accounts.throttles import LoginUsernameThrottle
from audit.models import ActivityLog
from rest_framework_tracking.models import APIRequestLog
from tests.builders import make_event
from tests.builders import make_user
from utils.drf_helper.throttling import FailClosedThrottle


pytestmark = pytest.mark.django_db

PASSWORD = 'not-a-real-password'
STRONG_PASSWORD = 'correct-horse-battery-7'


def _register(client=None, **overrides):
    body = {'username': 'alice', 'email': 'alice@example.com', 'password': STRONG_PASSWORD} | overrides
    return (client or APIClient()).post('/api/auth/register/', body, format='json')


def _login(username='buyer', password=PASSWORD, client=None):
    return (client or APIClient()).post('/api/auth/login/', {'username': username, 'password': password}, format='json')


def _refresh(refresh):
    return APIClient().post('/api/auth/refresh/', {'refresh': refresh}, format='json')


def test_register_creates_a_buyer_and_returns_tokens():
    response = _register()

    assert response.status_code == 201
    data = response.json()['data']
    user = User.objects.get(username='alice')
    assert data['user'] == {'uuid': str(user.uuid), 'username': 'alice', 'email': 'alice@example.com', 'role': 'buyer'}
    assert data['access']
    assert data['refresh']
    assert user.check_password(STRONG_PASSWORD)


def test_register_ignores_a_requested_role():
    _register(role='organizer', is_staff=True)

    user = User.objects.get(username='alice')
    assert user.role == User.Role.BUYER
    assert not user.is_staff


def test_register_writes_an_audit_row():
    _register()

    row = ActivityLog.objects.get(verb='user.registered')
    assert row.actor.username == 'alice'
    assert row.target_id == str(User.objects.get(username='alice').uuid)


def test_register_rejects_a_weak_password():
    response = _register(password='password')

    assert response.status_code == 400
    assert response.json()['status']['code'] == 'BAD_REQUEST'
    assert response.json()['status']['message'].startswith('[password]')
    assert not User.objects.filter(username='alice').exists()


def test_register_rejects_a_taken_username():
    make_user(username='alice')

    response = _register()

    assert response.status_code == 409
    assert response.json()['status']['code'] == 'USERNAME_TAKEN'
    assert not ActivityLog.objects.filter(verb='user.registered').exists()


def test_login_returns_a_token_pair():
    user = make_user()

    response = _login()

    assert response.status_code == 200
    data = response.json()['data']
    claims = jwt.decode(data['access'], settings.SECRET_KEY, algorithms=['HS256'])
    assert claims['user_id'] == str(user.uuid)
    assert claims['role'] == 'buyer'
    assert data['refresh']


@pytest.mark.parametrize('username, password', [('buyer', 'wrong-password'), ('nobody', PASSWORD)])
def test_login_failures_do_not_say_which_part_was_wrong(username, password):
    make_user()

    response = _login(username, password)

    assert response.status_code == 401
    assert response.json()['status'] == {'code': 'NOT_AUTHENTICATED', 'message': 'Authentication credentials were not provided or are invalid.'}


def test_an_inactive_account_cannot_log_in():
    make_user(is_active=False)

    assert _login().status_code == 401


def test_a_broken_access_token_does_not_block_login():
    make_user()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-token')

    assert _login(client=client).status_code == 200


def test_a_bearer_token_authenticates_an_api_call():
    make_user()
    access = _login().json()['data']['access']
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    response = client.post(f'/api/events/{make_event().uuid}/holds/', {'quantity': 1}, format='json', headers={'Idempotency-Key': 'k1'})

    assert response.status_code == 201


def test_a_garbage_bearer_token_is_refused_without_saying_why():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Bearer not-a-real-token')

    response = client.post(f'/api/events/{make_event().uuid}/holds/', {'quantity': 1}, format='json', headers={'Idempotency-Key': 'k1'})

    assert response.status_code == 401
    assert 'token_not_valid' not in response.content.decode()


def test_an_access_token_stops_working_when_the_account_is_disabled():
    user = make_user()
    access = _login().json()['data']['access']
    User.objects.filter(pk=user.pk).update(is_active=False)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    response = client.post(f'/api/events/{make_event().uuid}/holds/', {'quantity': 1}, format='json', headers={'Idempotency-Key': 'k1'})

    assert response.status_code == 401


def test_refresh_rotates_the_refresh_token():
    make_user()
    refresh = _login().json()['data']['refresh']

    response = _refresh(refresh)

    assert response.status_code == 200
    data = response.json()['data']
    assert data['access']
    assert data['refresh'] != refresh


def test_a_rotated_refresh_token_cannot_be_used_again():
    make_user()
    refresh = _login().json()['data']['refresh']
    _refresh(refresh)

    response = _refresh(refresh)

    assert response.status_code == 401
    assert response.json()['status']['code'] == 'NOT_AUTHENTICATED'


def test_a_garbage_refresh_token_is_refused_in_the_envelope():
    response = _refresh('not-a-real-token')

    assert response.status_code == 401
    assert response.json()['status']['code'] == 'NOT_AUTHENTICATED'
    assert 'token_not_valid' not in response.content.decode()


def test_a_refresh_token_of_a_deleted_account_is_refused():
    user = make_user()
    refresh = _login().json()['data']['refresh']
    user.delete()

    assert _refresh(refresh).status_code == 401


def test_a_refresh_token_of_a_disabled_account_is_refused():
    user = make_user()
    refresh = _login().json()['data']['refresh']
    User.objects.filter(pk=user.pk).update(is_active=False)

    assert _refresh(refresh).status_code == 401


def test_login_is_throttled_per_username_across_ips():
    make_user()
    rates = {**LoginUsernameThrottle.THROTTLE_RATES, 'login_username': '2/min'}

    with mock.patch.object(LoginUsernameThrottle, 'THROTTLE_RATES', rates):
        statuses = [_login(password='wrong', client=APIClient(REMOTE_ADDR=f'10.0.0.{n}')).status_code for n in range(3)]
        other_account = _login('someone-else', 'wrong', client=APIClient(REMOTE_ADDR='10.0.0.9')).status_code

    assert statuses == [401, 401, 429]
    assert other_account == 401


def test_the_username_throttle_ignores_case():
    make_user()
    rates = {**LoginUsernameThrottle.THROTTLE_RATES, 'login_username': '1/min'}

    with mock.patch.object(LoginUsernameThrottle, 'THROTTLE_RATES', rates):
        first = _login('buyer', 'wrong').status_code
        second = _login('BUYER', 'wrong').status_code

    assert (first, second) == (401, 429)


def test_login_and_register_share_one_ip_throttle():
    make_user()
    rates = {**AuthIPThrottle.THROTTLE_RATES, 'auth_ip': '2/min'}

    with mock.patch.object(AuthIPThrottle, 'THROTTLE_RATES', rates):
        statuses = [_login().status_code, _register().status_code, _register(username='bob').status_code]

    assert statuses == [200, 201, 429]


def test_login_fails_closed_when_the_throttle_store_is_down():
    make_user()
    broken_cache = mock.Mock(get=mock.Mock(side_effect=RedisConnectionError('down')))

    with mock.patch.object(FailClosedThrottle, 'cache', broken_cache):
        response = _login()

    assert response.status_code == 503
    assert response.json()['status']['code'] == 'SIGN_IN_PAUSED'


def test_refresh_works_while_the_throttle_store_is_down():
    make_user()
    refresh = _login().json()['data']['refresh']
    broken_cache = mock.Mock(get=mock.Mock(side_effect=RedisConnectionError('down')))

    with mock.patch.object(FailClosedThrottle, 'cache', broken_cache):
        response = _refresh(refresh)

    assert response.status_code == 200


def test_passwords_and_tokens_are_not_stored_in_request_logs():
    _register()
    _login('alice', 'guessed-password-42')

    stored = ' '.join(str(row.data) + str(row.response) for row in APIRequestLog.objects.all())
    assert APIRequestLog.objects.count() == 2
    assert STRONG_PASSWORD not in stored
    assert 'guessed-password-42' not in stored


def test_jwt_is_tried_before_session_and_basic_auth_is_off():
    classes = list(settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'])

    jwt_position = classes.index('rest_framework_simplejwt.authentication.JWTAuthentication')
    assert jwt_position < classes.index('rest_framework.authentication.SessionAuthentication')
    assert 'rest_framework.authentication.BasicAuthentication' not in classes


def test_rotated_refresh_tokens_can_be_blacklisted():
    assert 'rest_framework_simplejwt.token_blacklist' in settings.INSTALLED_APPS
    assert settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds() <= 15 * 60


@pytest.mark.parametrize('variant', ['buyer ', ' buyer', '\tbuyer\n', 'BUYER '])
def test_the_username_throttle_cannot_be_dodged_with_padding(variant):
    make_user()
    rates = {**LoginUsernameThrottle.THROTTLE_RATES, 'login_username': '1/min'}

    with mock.patch.object(LoginUsernameThrottle, 'THROTTLE_RATES', rates):
        first = _login('buyer', 'wrong').status_code
        second = _login(variant, PASSWORD).status_code

    assert (first, second) == (401, 429)


def test_the_username_throttle_counts_a_numeric_username():
    make_user(username='12345')
    rates = {**LoginUsernameThrottle.THROTTLE_RATES, 'login_username': '1/min'}

    with mock.patch.object(LoginUsernameThrottle, 'THROTTLE_RATES', rates):
        first = _login(12345, 'wrong').status_code
        second = _login('12345', PASSWORD).status_code

    assert (first, second) == (401, 429)


def test_a_password_with_surrounding_spaces_can_log_in():
    password = f'  {STRONG_PASSWORD}  '
    _register(password=password)

    assert _login('alice', password).status_code == 200
    assert _login('alice', STRONG_PASSWORD).status_code == 401


def test_register_rejects_an_email_longer_than_the_column():
    response = _register(email=f'{"a" * 64}@{"b" * 63}.{"c" * 63}.{"d" * 63}.example')

    assert response.status_code == 400
    assert response.json()['status']['message'].startswith('[email]')


def test_register_fails_closed_when_the_throttle_store_is_down():
    broken_cache = mock.Mock(get=mock.Mock(side_effect=RedisConnectionError('down')))

    with mock.patch.object(FailClosedThrottle, 'cache', broken_cache):
        response = _register()

    assert response.status_code == 503
    assert response.json()['status']['code'] == 'SIGN_IN_PAUSED'
    assert not User.objects.filter(username='alice').exists()


def test_me_returns_the_signed_in_user():
    user = make_user(username='alice', email='alice@example.test')
    client = APIClient()
    client.force_authenticate(user)

    response = client.get('/api/auth/me/')

    assert response.status_code == 200
    assert response.json()['data'] == {'uuid': str(user.uuid), 'username': 'alice', 'email': 'alice@example.test', 'role': 'buyer'}


def test_me_requires_sign_in():
    assert APIClient().get('/api/auth/me/').status_code == 401
