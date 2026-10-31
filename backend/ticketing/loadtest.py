from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db import transaction
from django.db.models import CharField
from django.db.models import Count
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.db.models.functions import Cast
from django.utils import timezone

from accounts.models import User
from audit.constants import ActivityVerb
from audit.services import log_action
from mockgateway.models import MockCharge
from payments.models import Payment
from payments.models import WebhookEvent
from reliability.models import DeadLetter
from reliability.models import OutboxMessage

from .mockdata import MOCK_ORGANIZER_USERNAME
from .models import Event
from .models import Hold
from .models import Order


@dataclass(frozen=True)
class LoadTestScenario:
    title: str
    capacity: int
    max_per_user: int
    opens_in: timedelta


SCENARIOS = {
    'flash': LoadTestScenario(title='Load Test Flash Sale', capacity=100, max_per_user=2, opens_in=timedelta(minutes=5)),
    'journey': LoadTestScenario(title='Load Test Journey', capacity=20000, max_per_user=100, opens_in=timedelta(0)),
}

HELD = (Hold.Status.ACTIVE, Hold.Status.CONVERTED)
# The relay publishes every 2 s; rows younger than this are in flight, not stuck.
OUTBOX_RELAY_GRACE = timedelta(seconds=10)
# Kombu's Redis transport keeps priorities 3, 6 and 9 in their own lists next to the plain queue name.
KOMBU_PRIORITY_SEPARATOR = '\x06\x16'
KOMBU_PRIORITY_STEPS = (3, 6, 9)
CELERY_QUEUES = ('critical', 'gateway', 'bulk')


@transaction.atomic
def seed_loadtest_event(
    *,
    scenario: str,
    capacity: int | None = None,
    max_per_user: int | None = None,
    opens_in: timedelta | None = None,
    now: datetime | None = None,
) -> Event:
    """Create a published event owned by the mock organizer, so `purge_mockdata` removes it with everything bought on it."""
    spec = SCENARIOS[scenario]
    now = now or timezone.now()
    capacity = spec.capacity if capacity is None else capacity
    opens_at = now + (spec.opens_in if opens_in is None else opens_in)
    organizer, _ = User.objects.get_or_create(
        username=MOCK_ORGANIZER_USERNAME,
        defaults={'email': '', 'role': User.Role.ORGANIZER, 'password': make_password(None)},
    )
    event = Event.objects.create(
        organizer=organizer,
        title=f'{spec.title} {opens_at:%Y-%m-%d %H:%M:%S}',
        summary='Synthetic event for a load test run.',
        category=Event.Category.OTHER,
        is_published=True,
        starts_at=now + timedelta(days=7),
        ends_at=now + timedelta(days=7, hours=3),
        sale_opens_at=opens_at,
        sale_closes_at=opens_at + timedelta(days=1),
        capacity=capacity,
        available=capacity,
        price_satang=50_000,
        max_per_user=spec.max_per_user if max_per_user is None else max_per_user,
    )
    log_action(ActivityVerb.MOCKDATA_SEEDED, target=event, detail={'loadtest': scenario, 'capacity': capacity})
    return event


def verify_event(event: Event, *, since: datetime | None = None) -> dict:
    """Check the stock and ticket invariants for one event; `ok` is false when any check fails."""
    with _snapshot():
        return _verify(event, since=since, now=timezone.now())


@contextmanager
def _snapshot():
    """Read every check from one snapshot, or a sweeper commit between two queries breaks `stock_balanced`."""
    outermost = not connection.in_atomic_block
    with transaction.atomic():
        if outermost:
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        yield


def _verify(event: Event, *, since: datetime | None, now: datetime) -> dict:
    event.refresh_from_db()
    holds = Hold.objects.filter(event=event)
    orders = Order.objects.filter(hold__event=event)
    payments = Payment.objects.filter(order__in=orders)
    payment_keys = payments.annotate(key=Cast('uuid', output_field=CharField())).values('key')
    succeeded_keys = payments.filter(status=Payment.Status.SUCCEEDED).annotate(key=Cast('uuid', output_field=CharField())).values('key')

    held_quantity = holds.filter(status__in=HELD).aggregate(total=Sum('quantity'))['total'] or 0
    paid = orders.filter(status=Order.Status.PAID).annotate(issued=Count('tickets'))
    # Same rule as create_hold: expired holds the sweeper has not reached yet no longer count toward the limit.
    counted = holds.filter(Q(status=Hold.Status.ACTIVE, expires_at__gt=now) | Q(status=Hold.Status.CONVERTED))
    over_limit = counted.values('user').annotate(total=Sum('quantity')).filter(total__gt=event.max_per_user)
    double_charged = payments.filter(status=Payment.Status.SUCCEEDED).values('order').annotate(n=Count('id')).filter(n__gt=1)
    dead_letters = DeadLetter.objects.filter(failed_at__gte=since) if since else DeadLetter.objects.all()
    # Charges the gateway settled whose payment was never recorded as succeeded, by webhook or by reconcile.
    unrecorded = (
        MockCharge.objects.filter(idempotency_key__in=payment_keys, status=MockCharge.Status.SUCCEEDED)
        .exclude(idempotency_key__in=succeeded_keys)
        .count()
    )

    checks = {
        'available_not_negative': event.available >= 0,
        'stock_balanced': event.available + held_quantity == event.capacity,
        'paid_orders_fully_ticketed': not paid.exclude(issued=F('hold__quantity')).exists(),
        'tickets_only_on_paid_orders': not orders.exclude(status=Order.Status.PAID).filter(tickets__isnull=False).exists(),
        'converted_holds_paid': not holds.filter(status=Hold.Status.CONVERTED).exclude(order__status=Order.Status.PAID).exists(),
        'paid_orders_converted': not paid.exclude(hold__status=Hold.Status.CONVERTED).exists(),
        'no_paid_unfulfilled': not orders.filter(status=Order.Status.PAID_UNFULFILLED).exists(),
        'within_per_user_limit': not over_limit.exists(),
        'single_successful_payment_per_order': not double_charged.exists(),
        'webhooks_processed': not WebhookEvent.objects.filter(payment_key__in=payment_keys, processed_at__isnull=True).exists(),
        'outbox_drained': not OutboxMessage.objects.filter(published_at__isnull=True, created_on__lt=now - OUTBOX_RELAY_GRACE).exists(),
        'no_dead_letters': not dead_letters.exists(),
        'charges_recorded': unrecorded == 0,
    }
    return {
        'event': str(event.uuid),
        'checked_at': now.isoformat(),
        'ok': all(checks.values()),
        'checks': checks,
        'stock': {'capacity': event.capacity, 'available': event.available, 'held': held_quantity},
        'holds': _count_by_status(holds),
        'orders': _count_by_status(orders),
        'payments': _count_by_status(payments),
        'tickets': paid.aggregate(total=Sum('issued'))['total'] or 0,
        'overdue_active_holds': holds.filter(status=Hold.Status.ACTIVE, expires_at__lt=now).count(),
        'charges_succeeded_unrecorded': unrecorded,
    }


def _count_by_status(queryset) -> dict[str, int]:
    return dict(queryset.order_by().values_list('status').annotate(n=Count('id')))


SAMPLE_FIELDS = (
    'sampled_at',
    'db_connections',
    'db_active',
    'db_idle_in_transaction',
    'db_max_connections',
    'queue_critical',
    'queue_gateway',
    'queue_bulk',
    'outbox_unpublished',
    'webhooks_unprocessed',
)


def sample_saturation(redis_client, *, now: datetime | None = None) -> dict:
    """One reading of the shared resources that saturate first: database connections and queue backlogs."""
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT count(*), count(*) FILTER (WHERE state = %s), count(*) FILTER (WHERE state = %s) '
            'FROM pg_stat_activity WHERE datname = current_database()',
            ['active', 'idle in transaction'],
        )
        total, active, idle_in_transaction = cursor.fetchone()
        cursor.execute('SHOW max_connections')
        max_connections = int(cursor.fetchone()[0])
    queues = {f'queue_{name}': queue_length(redis_client, name) for name in CELERY_QUEUES}
    return {
        'sampled_at': (now or timezone.now()).isoformat(),
        'db_connections': total,
        'db_active': active,
        'db_idle_in_transaction': idle_in_transaction,
        'db_max_connections': max_connections,
        **queues,
        'outbox_unpublished': OutboxMessage.objects.filter(published_at__isnull=True).count(),
        'webhooks_unprocessed': WebhookEvent.objects.filter(processed_at__isnull=True).count(),
    }


def queue_length(redis_client, name: str) -> int:
    keys = [name, *(f'{name}{KOMBU_PRIORITY_SEPARATOR}{step}' for step in KOMBU_PRIORITY_STEPS)]
    return sum(redis_client.llen(key) for key in keys)
