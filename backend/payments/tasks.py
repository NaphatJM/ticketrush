from celery import shared_task

from reliability.tasks import DeadLetterTask

from . import services


@shared_task(name='payments.process_succeeded', base=DeadLetterTask)
def process_succeeded(*, webhook_event_id: int) -> str:
    return services.apply_charge_succeeded(webhook_event_id=webhook_event_id)


@shared_task(name='payments.process_failed', base=DeadLetterTask)
def process_failed(*, webhook_event_id: int) -> str:
    return services.apply_charge_failed(webhook_event_id=webhook_event_id)
