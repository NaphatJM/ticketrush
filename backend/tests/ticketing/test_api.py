from datetime import timedelta
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient

from tests.builders import make_event
from tests.builders import make_user
from ticketing.models import Event
from ticketing.models import Hold
from ticketing.throttles import HoldUserThrottle
from utils.drf_helper.throttling import FailClosedThrottle


pytestmark = pytest.mark.django_db


@pytest.fixture
def buyer():
    return make_user()


@pytest.fixture
def api(buyer):
    client = APIClient()
    client.force_authenticate(buyer)
    return client


def _hold(api, event, quantity=1, key='key-1'):
    headers = {'Idempotency-Key': key} if key is not None else {}
    return api.post(f'/api/events/{event.uuid}/holds/', {'quantity': quantity}, format='json', headers=headers)


def test_events_are_listed_without_signing_in():
    event = make_event()

    response = APIClient().get('/api/events/')

    assert response.status_code == 200
    body = response.json()
    assert body['count'] == 1
    assert body['data'][0]['uuid'] == str(event.uuid)
    assert 'id' not in body['data'][0]


def test_event_detail_is_looked_up_by_uuid():
    event = make_event()

    response = APIClient().get(f'/api/events/{event.uuid}/')

    assert response.status_code == 200
    assert response.json()['data']['available'] == event.capacity


def test_a_hold_is_created_in_the_envelope(api):
    event = make_event()

    response = _hold(api, event, quantity=2)

    assert response.status_code == 201
    body = response.json()
    assert body['status']['code'] == 'SUCCESS'
    assert body['data']['event'] == str(event.uuid)
    assert body['data']['quantity'] == 2
    assert body['data']['status'] == 'active'
    assert response.headers['Idempotent-Replayed'] == 'false'


def test_holding_requires_sign_in():
    response = _hold(APIClient(), make_event())

    assert response.status_code == 401


def test_holding_requires_an_idempotency_key(api):
    response = _hold(api, make_event(), key=None)

    assert response.status_code == 400
    assert response.json()['status']['code'] == 'IDEMPOTENCY_KEY_REQUIRED'
    assert not Hold.objects.exists()


def test_a_repeated_key_replays_the_first_hold(api):
    event = make_event()
    first = _hold(api, event)

    second = _hold(api, event)

    assert second.status_code == 201
    assert second.json()['data'] == first.json()['data']
    assert second.headers['Idempotent-Replayed'] == 'true'
    assert Hold.objects.count() == 1
    assert Event.objects.get(pk=event.pk).available == event.capacity - 1


def test_a_reused_key_with_a_different_body_is_rejected(api):
    event = make_event()
    _hold(api, event, quantity=1)

    response = _hold(api, event, quantity=2)

    assert response.status_code == 422
    assert response.json()['status']['code'] == 'IDEMPOTENCY_KEY_REUSED'


def test_a_failed_hold_is_not_replayed(api):
    event = make_event(capacity=1, available=0)
    assert _hold(api, event).json()['status']['code'] == 'SOLD_OUT'
    Event.objects.filter(pk=event.pk).update(available=1)

    response = _hold(api, event)

    assert response.status_code == 201


def test_the_same_key_is_scoped_to_the_user(api):
    event = make_event()
    _hold(api, event)
    other = APIClient()
    other.force_authenticate(make_user(username='other'))

    response = _hold(other, event)

    assert response.status_code == 201
    assert Hold.objects.count() == 2


@pytest.mark.parametrize('quantity', [0, -1, 'two'])
def test_an_invalid_quantity_is_a_bad_request(api, quantity):
    response = _hold(api, make_event(), quantity=quantity)

    assert response.status_code == 400
    assert response.json()['status']['code'] == 'BAD_REQUEST'


def test_sold_out_is_a_conflict_with_its_code(api):
    response = _hold(api, make_event(capacity=1, available=0))

    assert response.status_code == 409
    assert response.json()['status']['code'] == 'SOLD_OUT'


def test_holds_are_throttled_per_user(api):
    event = make_event(capacity=50, max_per_user=50)
    rates = {**HoldUserThrottle.THROTTLE_RATES, 'holds_user': '2/min'}

    with mock.patch.object(HoldUserThrottle, 'THROTTLE_RATES', rates):
        statuses = [_hold(api, event, key=f'key-{n}').status_code for n in range(3)]

    assert statuses == [201, 201, 429]


def test_holds_fail_closed_when_the_throttle_store_is_down(api):
    event = make_event()
    broken_cache = mock.Mock(get=mock.Mock(side_effect=RedisConnectionError('down')))

    with mock.patch.object(FailClosedThrottle, 'cache', broken_cache):
        response = _hold(api, event)

    assert response.status_code == 503
    assert response.json()['status']['code'] == 'SALES_PAUSED'
    assert Event.objects.get(pk=event.pk).available == event.capacity


def test_a_hold_is_released_through_the_api(api, buyer):
    event = make_event()
    hold_uuid = _hold(api, event).json()['data']['uuid']

    response = api.delete(f'/api/holds/{hold_uuid}/')

    assert response.status_code == 200
    assert response.json()['data']['status'] == 'released'
    assert Event.objects.get(pk=event.pk).available == event.capacity


def test_another_users_hold_cannot_be_released(api):
    hold_uuid = _hold(api, make_event()).json()['data']['uuid']
    intruder = APIClient()
    intruder.force_authenticate(make_user(username='intruder'))

    response = intruder.delete(f'/api/holds/{hold_uuid}/')

    assert response.status_code == 404
    assert Hold.objects.get(uuid=hold_uuid).status == Hold.Status.ACTIVE


def test_unpublished_events_are_hidden_and_cannot_be_held(api):
    draft = make_event(is_published=False)
    make_event(title='Live')

    assert [event['title'] for event in APIClient().get('/api/events/').json()['data']] == ['Live']
    assert APIClient().get(f'/api/events/{draft.uuid}/').status_code == 404
    response = _hold(api, draft)
    assert response.status_code == 404
    assert Event.objects.get(pk=draft.pk).available == draft.capacity


def test_new_events_start_unpublished():
    assert Event._meta.get_field('is_published').default is False


@pytest.mark.parametrize(
    ('opens', 'closes', 'available', 'expected'),
    [
        (timedelta(hours=1), timedelta(hours=2), 10, 'upcoming'),
        (-timedelta(hours=1), timedelta(hours=1), 10, 'on_sale'),
        (-timedelta(hours=1), timedelta(hours=1), 0, 'sold_out'),
        (-timedelta(hours=2), -timedelta(hours=1), 0, 'closed'),
    ],
)
def test_sale_status_is_reported_and_filterable(opens, closes, available, expected):
    now = timezone.now()
    event = make_event(sale_opens_at=now + opens, sale_closes_at=now + closes, available=available)
    upcoming = {'sale_opens_at': now + timedelta(days=1), 'sale_closes_at': now + timedelta(days=2)}
    make_event(title='Other', **(upcoming if expected == 'on_sale' else {}))

    assert APIClient().get(f'/api/events/{event.uuid}/').json()['data']['sale_status'] == expected
    listed = APIClient().get('/api/events/', {'status': expected}).json()['data']
    assert [item['uuid'] for item in listed] == [str(event.uuid)]


def test_an_unknown_status_filter_is_rejected():
    response = APIClient().get('/api/events/', {'status': 'soon'})

    assert response.status_code == 400


def test_events_can_be_filtered_by_category():
    concert = make_event(category=Event.Category.CONCERT)
    make_event(category=Event.Category.SPORTS)

    listed = APIClient().get('/api/events/', {'category': 'concert'}).json()['data']

    assert [item['uuid'] for item in listed] == [str(concert.uuid)]


def test_the_list_omits_long_text_that_the_detail_returns():
    event = make_event(
        summary='Short', description='Long text', important_info='Bring ID', venue_address='1 Road', venue_map_url='https://maps.example/x'
    )

    listed = APIClient().get('/api/events/').json()['data'][0]
    detail = APIClient().get(f'/api/events/{event.uuid}/').json()['data']

    assert listed['summary'] == 'Short'
    assert 'description' not in listed
    assert (detail['description'], detail['important_info'], detail['venue_address'], detail['venue_map_url']) == (
        'Long text',
        'Bring ID',
        '1 Road',
        'https://maps.example/x',
    )


def test_banner_and_map_urls_must_use_https():
    event = make_event(banner_url='http://example.test/banner.jpg', venue_map_url='http://maps.example/x')

    with pytest.raises(ValidationError) as excinfo:
        event.full_clean()

    assert set(excinfo.value.message_dict) == {'banner_url', 'venue_map_url'}


def test_an_event_cannot_end_before_it_starts():
    now = timezone.now()

    with pytest.raises(IntegrityError):
        make_event(starts_at=now + timedelta(days=2), ends_at=now + timedelta(days=1))
