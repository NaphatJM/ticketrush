from datetime import timedelta

import pytest
from django.utils import timezone

from reliability.exceptions import IdempotencyInProgress
from reliability.exceptions import IdempotencyKeyRequired
from reliability.models import IdempotencyRecord
from reliability.services import request_fingerprint
from reliability.services import run_idempotent
from tests.builders import make_user


pytestmark = pytest.mark.django_db


def _run(user, key='key-1', payload=None, body='first'):
    return run_idempotent(user=user, key=key, endpoint='test', payload=payload or {'a': 1}, action=lambda: (201, body))


def test_the_body_fingerprint_ignores_key_order():
    assert request_fingerprint({'a': 1, 'b': 2}) == request_fingerprint({'b': 2, 'a': 1})


@pytest.mark.parametrize('key', [None, '', 'has space', 'x' * 129, 'ไทย'])
def test_a_missing_or_malformed_key_is_rejected(key):
    with pytest.raises(IdempotencyKeyRequired):
        _run(make_user(), key=key)


def test_a_completed_record_stores_the_response():
    user = make_user()

    result = _run(user)

    record = IdempotencyRecord.objects.get()
    assert (result.status_code, result.body, result.replayed) == (201, 'first', False)
    assert (record.state, record.response_status, record.response_body) == ('complete', 201, 'first')


def test_a_record_still_pending_is_reported_in_progress():
    user = make_user()
    IdempotencyRecord.objects.create(
        user=user, key='key-1', endpoint='test', request_hash=request_fingerprint({'a': 1}), expires_at=timezone.now() + timedelta(hours=1)
    )

    with pytest.raises(IdempotencyInProgress):
        _run(user)


def test_an_expired_record_lets_the_key_run_again():
    user = make_user()
    _run(user)
    IdempotencyRecord.objects.update(expires_at=timezone.now() - timedelta(seconds=1))

    result = _run(user, payload={'a': 2}, body='second')

    assert (result.body, result.replayed) == ('second', False)
    assert IdempotencyRecord.objects.get().response_body == 'second'
