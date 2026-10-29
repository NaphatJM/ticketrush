from unittest import mock

import pytest
from celery import Task
from celery.exceptions import Reject
from celery.exceptions import Retry
from django.db import transaction
from kombu.exceptions import OperationalError as BrokerError

from audit.models import ActivityLog
from payments.models import WebhookEvent
from payments.tasks import process_succeeded
from reliability import outbox
from reliability.models import DeadLetter
from reliability.models import OutboxMessage
from reliability.tasks import relay_outbox
from tests.builders import make_user


pytestmark = pytest.mark.django_db

TOPIC = 'payments.process_succeeded'


@pytest.fixture
def apply_async():
    with mock.patch('payments.tasks.process_succeeded.apply_async') as patched:
        yield patched


def test_a_message_is_published_once_its_transaction_commits(apply_async, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        message = outbox.enqueue(TOPIC, {'webhook_event_id': 7})

    apply_async.assert_called_once_with(kwargs={'webhook_event_id': 7}, retry=False)
    message.refresh_from_db()
    assert message.published_at is not None


def test_a_rolled_back_transaction_publishes_nothing(apply_async, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True), pytest.raises(RuntimeError), transaction.atomic():
        outbox.enqueue(TOPIC, {'webhook_event_id': 7})
        raise RuntimeError

    apply_async.assert_not_called()
    assert not OutboxMessage.objects.exists()


def test_a_broker_outage_keeps_the_message_for_the_relay(apply_async, django_capture_on_commit_callbacks):
    apply_async.side_effect = BrokerError('redis down')

    with django_capture_on_commit_callbacks(execute=True):
        message = outbox.enqueue(TOPIC, {'webhook_event_id': 7})

    message.refresh_from_db()
    assert message.published_at is None
    assert message.attempts == 1
    assert 'redis down' in message.last_error


def test_the_relay_publishes_pending_messages_in_order(apply_async):
    first = OutboxMessage.objects.create(topic=TOPIC, payload={'webhook_event_id': 1})
    second = OutboxMessage.objects.create(topic=TOPIC, payload={'webhook_event_id': 2})

    assert relay_outbox() == 2

    assert [call.kwargs['kwargs'] for call in apply_async.call_args_list] == [first.payload, second.payload]
    assert not OutboxMessage.objects.filter(published_at__isnull=True).exists()


def test_a_message_that_keeps_failing_becomes_a_dead_letter(apply_async):
    apply_async.side_effect = BrokerError('redis down')
    OutboxMessage.objects.create(topic=TOPIC, payload={'webhook_event_id': 1}, attempts=outbox.MAX_PUBLISH_ATTEMPTS - 1)

    assert relay_outbox() == 0

    assert not OutboxMessage.objects.exists()
    letter = DeadLetter.objects.get()
    assert (letter.task_name, letter.args) == (TOPIC, {'webhook_event_id': 1})


def test_an_unknown_topic_is_counted_as_a_failed_publish():
    message = OutboxMessage.objects.create(topic='no.such.task', payload={})

    relay_outbox()

    message.refresh_from_db()
    assert (message.published_at, message.attempts) == (None, 1)


def test_a_failing_task_is_retried_before_it_is_dead_lettered():
    with pytest.raises(Retry):
        process_succeeded.delay(webhook_event_id=999_999)

    assert not DeadLetter.objects.exists()


def test_a_task_that_exhausts_its_retries_becomes_a_dead_letter():
    result = process_succeeded.apply(kwargs={'webhook_event_id': 999_999}, retries=process_succeeded.max_retries, throw=False)

    assert isinstance(result.result, WebhookEvent.DoesNotExist)

    letter = DeadLetter.objects.get()
    assert (letter.task_name, letter.args) == ('payments.process_succeeded', {'webhook_event_id': 999_999})
    assert 'DoesNotExist' in letter.error


def test_a_retry_the_broker_cannot_accept_becomes_a_dead_letter():
    # Celery raises Reject when it cannot publish the retry, then acks the task without calling on_failure.
    with mock.patch.object(Task, 'retry', side_effect=Reject(BrokerError('broker down'), requeue=False)):
        process_succeeded.apply(kwargs={'webhook_event_id': 999_999}, throw=False)

    letter = DeadLetter.objects.get()
    assert (letter.task_name, letter.args) == ('payments.process_succeeded', {'webhook_event_id': 999_999})
    assert 'broker down' in letter.error


def test_staff_can_replay_a_dead_letter_once(client, apply_async, django_capture_on_commit_callbacks):
    client.force_login(make_user(username='ops', is_staff=True, is_superuser=True))
    letter = DeadLetter.objects.create(task_name=TOPIC, args={'webhook_event_id': 3}, error='boom')

    with django_capture_on_commit_callbacks(execute=True):
        for _ in range(2):
            client.post('/admin/reliability/deadletter/', {'action': 'replay', '_selected_action': [letter.pk]})

    apply_async.assert_called_once_with(kwargs={'webhook_event_id': 3})
    letter.refresh_from_db()
    assert letter.replayed_at is not None
    assert ActivityLog.objects.filter(verb='dead_letter.replayed').count() == 1
