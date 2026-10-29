import logging

from celery import Task
from celery import shared_task
from celery.exceptions import Reject

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

    def retry(self, *args, **kwargs):
        try:
            return super().retry(*args, **kwargs)
        except Reject as reject:
            # Celery acks a task whose retry cannot be published and never calls on_failure, so record it here.
            self._dead_letter(reject.reason, task_id=self.request.id, kwargs=self.request.kwargs)
            raise

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        self._dead_letter(exc, task_id=task_id, kwargs=kwargs)

    def _dead_letter(self, exc, *, task_id, kwargs) -> None:
        DeadLetter.objects.create(task_name=self.name, args=kwargs, error=f'{type(exc).__name__}: {exc}'[:2000])
        logger.error('task dead-lettered', extra={'task': self.name, 'task_id': task_id}, exc_info=exc)


@shared_task(name='outbox.relay')
def relay_outbox() -> int:
    return outbox.publish_pending()
