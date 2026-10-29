from celery import shared_task

from . import services


@shared_task(name='accounts.flush_expired_tokens')
def flush_expired_tokens() -> int:
    return services.flush_expired_tokens()
