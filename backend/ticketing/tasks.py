from celery import shared_task

from . import services


@shared_task(name='holds.expire_sweeper')
def expire_holds() -> int:
    return services.expire_holds()
