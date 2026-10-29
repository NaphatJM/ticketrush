import inspect

import pytest

from rest_framework_tracking.mixins import TrackingMixin


pytestmark = pytest.mark.django_db


@pytest.fixture
def schema(client):
    response = client.get('/system/schema/?format=json')
    assert response.status_code == 200
    return response.json()


def _operations(schema):
    for path, methods in schema['paths'].items():
        for method, operation in methods.items():
            yield f'{method.upper()} {path}', operation


def _resolve(schema, node):
    while '$ref' in node:
        node = schema['components']['schemas'][node['$ref'].rsplit('/', 1)[-1]]
    return node


def test_every_operation_has_its_own_summary_description_and_tag(schema):
    mixin_doc = inspect.getdoc(TrackingMixin)

    for name, operation in _operations(schema):
        assert operation.get('summary'), name
        assert operation.get('description'), name
        assert operation['description'] != mixin_doc, name
        assert operation['tags'] != ['api'], name


def test_every_documented_response_matches_the_envelope(schema):
    for name, operation in _operations(schema):
        for code, response in operation['responses'].items():
            body = _resolve(schema, response['content']['application/json']['schema'])
            expected = {'status', 'data'} if code.startswith('2') else {'status', 'trace'}
            assert expected <= set(body['properties']), f'{name} {code}'
            assert expected <= set(body['required']), f'{name} {code}'


def test_paginated_lists_document_the_real_page_shape(client, schema):
    documented = _resolve(schema, schema['paths']['/api/events/']['get']['responses']['200']['content']['application/json']['schema'])

    actual = client.get('/api/events/').json()

    assert set(documented['properties']) == set(actual)
    assert set(documented['properties']['links']['properties']) == set(actual['links'])
