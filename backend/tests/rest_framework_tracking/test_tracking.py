from unittest import mock

import pytest
from django.test import override_settings
from django_guid import set_guid
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from rest_framework_tracking.models import APIRequestLog
from utils.drf_helper.views import APIView


pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class LoginLikeView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        return Response(self.encap_success_overhead({'ok': True}))

    def post(self, request):
        return Response(self.encap_success_overhead({'access': 'jwt-access-token'}))


class MissingView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        raise NotFound


def test_a_write_is_stored_with_secrets_redacted():
    set_guid('cid-write')

    LoginLikeView.as_view()(factory.post('/api/auth/login/?next=x', {'username': 'buyer', 'password': 'hunter2'}, format='json'))

    log = APIRequestLog.objects.get()
    assert log.method == 'POST'
    assert log.status_code == 200
    assert log.cid == 'cid-write'
    assert log.data == {'username': 'buyer', 'password': '********'}
    assert log.query_params == {'next': ['x']}


def test_a_successful_response_body_is_not_stored():
    LoginLikeView.as_view()(factory.post('/', {}, format='json'))

    assert APIRequestLog.objects.get().response is None


def test_a_fast_successful_read_is_not_stored():
    LoginLikeView.as_view()(factory.get('/'))

    assert not APIRequestLog.objects.exists()


@override_settings(DRF_TRACKING_SLOW_MS=0)
def test_a_slow_read_is_stored():
    LoginLikeView.as_view()(factory.get('/'))

    assert APIRequestLog.objects.count() == 1


def test_an_error_read_is_stored_with_its_response():
    MissingView.as_view()(factory.get('/missing/'))

    log = APIRequestLog.objects.get()
    assert log.status_code == 404
    assert log.response['status']['code'] == 'NOT_FOUND'


def test_a_tracking_failure_does_not_fail_the_request():
    with mock.patch.object(APIRequestLog.objects, 'create', side_effect=RuntimeError('db down')):
        response = LoginLikeView.as_view()(factory.post('/', {}, format='json'))

    assert response.status_code == 200
