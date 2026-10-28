import pytest
from rest_framework import serializers
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from utils.drf_helper.views import APIView


pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class SoldOutError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'sold_out'
    default_detail = 'Tickets for this event are sold out.'

    def __init__(self, event_id: str):
        super().__init__()
        self.trace = {'event_id': event_id}


class QuantitySerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class EchoView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = QuantitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(self.encap_success_overhead(serializer.validated_data))


class SoldOutView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        raise SoldOutError(event_id='evt-1')


class BrokenView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        raise RuntimeError('database exploded')


class PrivateView(APIView):
    def get(self, request):
        return Response(self.encap_success_overhead({}))


def test_success_is_wrapped_in_the_envelope():
    response = EchoView.as_view()(factory.post('/', {'quantity': 2}, format='json'))

    assert response.status_code == 200
    assert response.data == {'status': {'code': 'SUCCESS', 'message': 'Success.'}, 'data': {'quantity': 2}}


def test_validation_errors_are_flattened_per_field():
    response = EchoView.as_view()(factory.post('/', {'quantity': 0}, format='json'))

    assert response.status_code == 400
    assert response.data['status']['code'] == 'BAD_REQUEST'
    assert response.data['status']['message'].startswith('[quantity] ')
    assert response.data['trace'] == {}


def test_domain_errors_expose_their_code_and_trace():
    response = SoldOutView.as_view()(factory.post('/', {}, format='json'))

    assert response.status_code == 409
    assert response.data == {
        'status': {'code': 'SOLD_OUT', 'message': 'Tickets for this event are sold out.'},
        'trace': {'event_id': 'evt-1'},
    }


def test_unexpected_errors_hide_their_detail():
    response = BrokenView.as_view()(factory.post('/', {}, format='json'))

    assert response.status_code == 500
    assert response.data['status']['code'] == 'INTERNAL_SERVER_ERROR'
    assert 'exploded' not in str(response.data)


def test_anonymous_callers_get_not_authenticated():
    response = PrivateView.as_view()(factory.get('/'))

    assert response.status_code in {401, 403}
    assert response.data['status']['code'] in {'NOT_AUTHENTICATED', 'FORBIDDEN'}
