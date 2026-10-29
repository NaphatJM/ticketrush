import logging

from celery import Task
from celery import shared_task

from . import outbox
from .models import DeadLetter


logger = logging.getLogger(__name__)

#: Must stay below the broker visibility timeout, or Redis redelivers a task while its retry is still waiting.
RETRY_BACKOFF_MAX_SECONDS = 240


class DeadLetterTask(Task):
    """Retries with exponential backoff and jitter, then records a dead letter. Tasks take keyword arguments only, so a replay can resend them."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = RETRY_BACKOFF_MAX_SECONDS
    retry_jitter = True
    max_retries = 5

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        DeadLetter.objects.create(task_name=self.name, args=kwargs, error=f'{type(exc).__name__}: {exc}'[:2000])
        logger.error('task dead-lettered', extra={'task': self.name, 'task_id': task_id}, exc_info=exc)


@shared_task(name='outbox.relay')
def relay_outbox() -> int:
    return outbox.publish_pending()
