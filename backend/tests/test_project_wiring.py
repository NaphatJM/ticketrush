from unittest import mock

import pytest
from django.db.utils import OperationalError
from django.test import override_settings

from tests.builders import make_user


pytestmark = pytest.mark.django_db


def test_healthcheck_answers_without_touching_dependencies(client):
    with mock.patch('ticketrush.views.check_postgres', side_effect=OperationalError):
        response = client.get('/system/healthcheck/')

    assert response.status_code == 200
    assert response.json() == {'status': 'healthy'}


def test_readiness_is_ready_when_postgres_answers(client):
    response = client.get('/system/readiness/')

    assert response.status_code == 200
    assert response.json() == {'status': 'ready'}


def test_readiness_ignores_a_redis_outage(client):
    with mock.patch('ticketrush.views.check_redis', side_effect=ConnectionError):
        response = client.get('/system/readiness/')

    assert response.status_code == 200


def test_readiness_fails_when_postgres_is_down(client):
    with mock.patch('ticketrush.views.check_postgres', side_effect=OperationalError):
        response = client.get('/system/readiness/')

    assert response.status_code == 503
    assert response.json() == {'status': 'unavailable'}


def test_dependencies_is_forbidden_to_anonymous_callers(client):
    response = client.get('/system/dependencies/')

    assert response.status_code == 403
    assert 'checks' not in response.json()


@override_settings(READINESS_TOKEN='probe-token')
def test_dependencies_accepts_the_readiness_token(client):
    response = client.get('/system/dependencies/', headers={'X-Readiness-Token': 'probe-token'})

    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'checks': {'postgres': 'ok', 'redis': 'ok'}}


@override_settings(READINESS_TOKEN='probe-token')
def test_dependencies_rejects_a_wrong_token(client):
    response = client.get('/system/dependencies/', headers={'X-Readiness-Token': 'wrong'})

    assert response.status_code == 403


def test_dependencies_reports_a_redis_outage_to_staff(client):
    client.force_login(make_user(is_staff=True))

    with mock.patch('ticketrush.views.check_redis', side_effect=ConnectionError):
        response = client.get('/system/dependencies/')

    assert response.status_code == 503
    assert response.json()['checks'] == {'postgres': 'ok', 'redis': 'fail'}


def test_the_openapi_schema_generates(client):
    response = client.get('/system/schema/')

    assert response.status_code == 200


def test_admin_is_not_on_the_default_path(client):
    assert client.get('/admin/').status_code == 404
    assert client.get('/staff-admin/').status_code == 302


def test_every_response_returns_the_correlation_id(client):
    response = client.get('/system/healthcheck/')

    assert response.headers['Correlation-ID']


def test_probes_accept_head_requests(client):
    assert client.head('/system/healthcheck/').status_code == 200
    assert client.head('/system/readiness/').status_code == 200
