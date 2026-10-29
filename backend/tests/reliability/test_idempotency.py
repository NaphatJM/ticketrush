from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from reliability.exceptions import IdempotencyInProgress
from reliability.exceptions import IdempotencyKeyRequired
from reliability.models import IdempotencyRecord
from reliability.services import PENDING_LEASE
from reliability.services import request_fingerprint
from reliability.services import run_idempotent
from reliability.services import run_idempotent_two_phase
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


def _two_phase(user, *, key='key-1', prepare=lambda: 'prepared', perform=lambda prepared: (201, prepared)):
    return run_idempotent_two_phase(user=user, key=key, endpoint='test', payload={'a': 1}, prepare=prepare, perform=perform)


def test_two_phase_commits_a_pending_record_before_the_external_call():
    user = make_user()
    seen = []

    def perform(prepared):
        seen.append(IdempotencyRecord.objects.get().state)
        return 201, prepared

    result = _two_phase(user, perform=perform)

    assert seen == ['pending']
    assert (result.body, result.replayed) == ('prepared', False)
    assert IdempotencyRecord.objects.get().state == 'complete'


def test_two_phase_replays_a_completed_request_without_preparing_again():
    user = make_user()
    _two_phase(user)
    prepare = mock.Mock()

    result = _two_phase(user, prepare=prepare)

    prepare.assert_not_called()
    assert (result.body, result.replayed) == ('prepared', True)


def test_two_phase_rejects_a_duplicate_while_the_first_is_in_flight():
    user = make_user()

    def perform(prepared):
        with pytest.raises(IdempotencyInProgress):
            _two_phase(user)
        return 201, prepared

    _two_phase(user, perform=perform)


def test_a_failed_external_call_frees_the_key_for_a_retry():
    user = make_user()

    with pytest.raises(RuntimeError):
        _two_phase(user, perform=mock.Mock(side_effect=RuntimeError))

    assert not IdempotencyRecord.objects.exists()
    assert _two_phase(user).replayed is False


def test_a_failed_prepare_leaves_no_record():
    with pytest.raises(RuntimeError):
        _two_phase(make_user(), prepare=mock.Mock(side_effect=RuntimeError))

    assert not IdempotencyRecord.objects.exists()


def test_a_pending_record_past_its_lease_is_taken_over():
    user = make_user()
    record = IdempotencyRecord.objects.create(
        user=user, key='key-1', endpoint='test', request_hash=request_fingerprint({'a': 1}), expires_at=timezone.now() + timedelta(hours=1)
    )
    IdempotencyRecord.objects.filter(pk=record.pk).update(created_on=timezone.now() - PENDING_LEASE - timedelta(seconds=1))

    result = _two_phase(user)

    assert result.replayed is False
    assert IdempotencyRecord.objects.get().state == 'complete'
