import functools
import time
from collections.abc import Callable
from collections.abc import Iterable

import redis
from celery.signals import before_task_publish
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Min
from django.utils import timezone
from opentelemetry import metrics
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.metrics import CallbackOptions
from opentelemetry.metrics import Observation

from payments.models import WebhookEvent
from reliability.models import DeadLetter
from reliability.models import OutboxMessage
from ticketing.loadtest import CELERY_QUEUES
from ticketing.loadtest import queue_length
from ticketing.models import Event


#: Caps the per-event stock series; only events inside their sale window are reported.
MAX_EVENTS_REPORTED = 20

_last_publish = time.monotonic()


def register() -> None:
    before_task_publish.connect(_mark_publish, weak=False)
    meter = metrics.get_meter(__name__)
    meter.create_observable_gauge(
        'ticketrush.beat.publish_age', [beat_publish_age], unit='s', description='Seconds since beat sent a task; the outbox relay is due every 2 s.'
    )
    meter.create_observable_gauge('ticketrush.celery.queue.length', [queue_lengths], unit='{task}', description='Tasks waiting in each broker queue.')
    meter.create_observable_gauge('ticketrush.outbox.unpublished', [outbox_unpublished], unit='{message}')
    meter.create_observable_gauge('ticketrush.outbox.oldest_age', [outbox_oldest_age], unit='s', description='Age of the oldest unpublished row.')
    meter.create_observable_gauge('ticketrush.dead_letters.pending', [dead_letters_pending], unit='{task}', description='Dead letters not replayed.')
    meter.create_observable_gauge('ticketrush.webhooks.unprocessed', [webhooks_unprocessed], unit='{event}')
    meter.create_observable_gauge(
        'ticketrush.event.available', [events_available], unit='{ticket}', description='Stock left per event, by event UUID, in its sale window.'
    )


def _mark_publish(**kwargs) -> None:
    global _last_publish  # noqa: PLW0603
    _last_publish = time.monotonic()


def _untraced_reading(callback: Callable[[], list[Observation]]) -> Callable[[CallbackOptions], Iterable[Observation]]:
    """Run on the metric reader's thread, so it reconnects like a request would and records no spans for its own queries."""

    @functools.wraps(callback)
    def observe(options: CallbackOptions) -> Iterable[Observation]:
        with suppress_instrumentation():
            close_old_connections()
            return callback()

    return observe


@_untraced_reading
def beat_publish_age() -> list[Observation]:
    return [Observation(time.monotonic() - _last_publish)]


@_untraced_reading
def queue_lengths() -> list[Observation]:
    client = _broker()
    return [Observation(queue_length(client, name), {'queue': name}) for name in CELERY_QUEUES]


@_untraced_reading
def outbox_unpublished() -> list[Observation]:
    return [Observation(OutboxMessage.objects.filter(published_at__isnull=True).count())]


@_untraced_reading
def outbox_oldest_age() -> list[Observation]:
    oldest = OutboxMessage.objects.filter(published_at__isnull=True).aggregate(oldest=Min('created_on'))['oldest']
    return [Observation((timezone.now() - oldest).total_seconds() if oldest else 0)]


@_untraced_reading
def dead_letters_pending() -> list[Observation]:
    return [Observation(DeadLetter.objects.filter(replayed_at__isnull=True).count())]


@_untraced_reading
def webhooks_unprocessed() -> list[Observation]:
    return [Observation(WebhookEvent.objects.filter(processed_at__isnull=True).count())]


@_untraced_reading
def events_available() -> list[Observation]:
    now = timezone.now()
    events = Event.objects.filter(is_published=True, sale_opens_at__lte=now, sale_closes_at__gt=now).order_by('sale_opens_at', 'id')
    return [Observation(available, {'event': str(uuid)}) for uuid, available in events.values_list('uuid', 'available')[:MAX_EVENTS_REPORTED]]


@functools.cache
def _broker() -> redis.Redis:
    return redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2, socket_timeout=5)
