import functools
import logging
from typing import Any

from celery import Task
from celery import current_app
from django.db import transaction
from django.utils import timezone

from .models import DeadLetter
from .models import OutboxMessage


logger = logging.getLogger(__name__)

RELAY_BATCH_SIZE = 100
MAX_PUBLISH_ATTEMPTS = 10


def enqueue(topic: str, payload: dict[str, Any]) -> OutboxMessage:
    """Write a task to the outbox inside the caller's transaction; it is published only if that transaction commits."""
    message = OutboxMessage.objects.create(topic=topic, payload=payload)
    transaction.on_commit(lambda: publish_pending(ids=[message.pk], retry=False))
    return message


def publish_pending(*, ids: list[int] | None = None, batch_size: int = RELAY_BATCH_SIZE, retry: bool = True) -> int:
    """Publish unpublished rows and return how many reached the broker.

    A broker error never escapes: the row keeps its error and attempt count, and the relay tries it again.
    """
    published = 0
    with transaction.atomic():
        rows = OutboxMessage.objects.select_for_update(skip_locked=True).filter(published_at__isnull=True).order_by('id')
        if ids is not None:
            rows = rows.filter(pk__in=ids)
        for message in rows[:batch_size]:
            if _publish(message, retry=retry):
                published += 1
    return published


def task_by_name(name: str) -> Task:
    _import_task_modules()
    return current_app.tasks[name]


@functools.cache
def _import_task_modules() -> None:
    # Celery's autodiscovery runs only when a worker starts, so web processes import the task modules here.
    current_app.loader.import_default_modules()


def _publish(message: OutboxMessage, *, retry: bool) -> bool:
    try:
        task_by_name(message.topic).apply_async(kwargs=message.payload, retry=retry)
    except Exception as exc:
        message.attempts += 1
        message.last_error = f'{type(exc).__name__}: {exc}'[:2000]
        if message.attempts >= MAX_PUBLISH_ATTEMPTS:
            DeadLetter.objects.create(task_name=message.topic, args=message.payload, error=message.last_error)
            message.delete()
            logger.error('outbox message dead-lettered', extra={'topic': message.topic, 'attempts': message.attempts})
        else:
            message.save(update_fields=['attempts', 'last_error'])
            logger.warning('outbox publish failed', extra={'topic': message.topic, 'attempts': message.attempts}, exc_info=exc)
        return False

    message.published_at = timezone.now()
    message.save(update_fields=['published_at'])
    return True
