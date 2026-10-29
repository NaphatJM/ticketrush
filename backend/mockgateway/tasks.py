import json
import logging
import random
import urllib.request

from celery import shared_task
from django.conf import settings

from reliability.tasks import DeadLetterTask

from . import signing
from .models import FaultConfig


logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5


@shared_task(name='mockgateway.deliver_webhook', base=DeadLetterTask)
def deliver_webhook(*, event: dict) -> int:
    """POST the signed event to the API, applying the configured drop and duplicate rates; returns how many copies were sent."""
    config = FaultConfig.load()
    if random.random() < config.drop_webhook_rate:  # noqa: S311
        logger.warning('mock webhook dropped', extra={'webhook_event_id': event['id']})
        return 0
    copies = 2 if random.random() < config.duplicate_webhook_rate else 1  # noqa: S311
    for _ in range(copies):
        post_event(event)
    return copies


def post_event(event: dict) -> None:
    url = f'{settings.PUBLIC_API_URL}/api/webhooks/mock/'
    if not url.startswith(('https://', 'http://')):
        raise ValueError('DJANGO_PUBLIC_API_URL must be an http(s) URL')
    body = json.dumps(event, separators=(',', ':')).encode()
    request = urllib.request.Request(  # noqa: S310
        url,
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json', signing.SIGNATURE_HEADER: signing.sign(body, secret=settings.MOCK_GATEWAY_WEBHOOK_SECRET)},
    )
    with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:  # noqa: S310
        logger.info('mock webhook delivered', extra={'webhook_event_id': event['id'], 'status': response.status})
