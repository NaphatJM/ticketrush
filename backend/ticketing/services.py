import logging
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.db.models import Q
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound

from audit.constants import ActivityVerb
from audit.services import log_action

from .exceptions import HoldHasOrder
from .exceptions import HoldNotActive
from .exceptions import PerUserLimit
from .exceptions import SaleNotOpen
from .exceptions import SoldOut
from .models import Event
from .models import Hold
from .models import Order


logger = logging.getLogger(__name__)

HOLD_TTL = timedelta(minutes=5)
EXPIRE_BATCH_SIZE = 500


def create_hold(*, user, event_uuid, quantity: int) -> Hold:
    now = timezone.now()
    with transaction.atomic():
        event = Event.objects.filter(uuid=event_uuid, is_published=True).first()
        if event is None:
            raise NotFound
        if quantity > event.max_per_user:
            raise PerUserLimit

        # A single conditional UPDATE: Postgres re-checks the WHERE after waiting on the row lock, so stock never goes negative.
        reserved = Event.objects.filter(
            pk=event.pk,
            available__gte=quantity,
            sale_opens_at__lte=now,
            sale_closes_at__gt=now,
        ).update(available=F('available') - quantity, updated_on=now)
        if not reserved:
            if not event.sale_opens_at <= now < event.sale_closes_at:
                raise SaleNotOpen
            raise SoldOut

        # The event row is locked from here to commit, so concurrent holds by the same user count each other.
        already = (
            Hold.objects.filter(user=user, event=event)
            .filter(Q(status=Hold.Status.ACTIVE, expires_at__gt=now) | Q(status=Hold.Status.CONVERTED))
            .aggregate(total=Sum('quantity'))['total']
            or 0
        )
        if already + quantity > event.max_per_user:
            raise PerUserLimit

        hold = Hold.objects.create(event=event, user=user, quantity=quantity, expires_at=now + HOLD_TTL)
        log_action(ActivityVerb.HOLD_CREATED, actor=user, target=hold, detail={'event': str(event.uuid), 'quantity': quantity})
    logger.info('hold created', extra={'event_id': str(event.uuid), 'quantity': quantity})
    return hold


def release_hold(*, user, hold_uuid) -> Hold:
    now = timezone.now()
    with transaction.atomic():
        # Locking the hold orders this against checkout, which locks it before creating an order.
        hold = Hold.objects.select_for_update().filter(uuid=hold_uuid, user=user).first()
        if hold is None:
            raise NotFound
        if Order.objects.filter(hold=hold).exists():
            raise HoldHasOrder
        released = Hold.objects.filter(pk=hold.pk, status=Hold.Status.ACTIVE).update(status=Hold.Status.RELEASED, updated_on=now)
        if not released:
            raise HoldNotActive
        Event.objects.filter(pk=hold.event_id).update(available=F('available') + hold.quantity, updated_on=now)
        log_action(ActivityVerb.HOLD_RELEASED, actor=user, target=hold, detail={'quantity': hold.quantity})
    hold.refresh_from_db()
    return hold


def expire_holds(*, batch_size: int = EXPIRE_BATCH_SIZE) -> int:
    """Expire one batch of active holds past `expires_at`, return their stock, and expire their pending orders."""
    now = timezone.now()
    with transaction.atomic():
        holds = list(
            Hold.objects.select_for_update(skip_locked=True)
            .filter(status=Hold.Status.ACTIVE, expires_at__lte=now)
            .order_by('expires_at')[:batch_size]
        )
        if not holds:
            return 0

        hold_ids = [hold.pk for hold in holds]
        Hold.objects.filter(pk__in=hold_ids, status=Hold.Status.ACTIVE).update(status=Hold.Status.EXPIRED, updated_on=now)

        returned: dict[int, int] = defaultdict(int)
        for hold in holds:
            returned[hold.event_id] += hold.quantity
        # Fixed lock order across concurrent sweepers.
        for event_id in sorted(returned):
            Event.objects.filter(pk=event_id).update(available=F('available') + returned[event_id], updated_on=now)

        Order.objects.filter(hold_id__in=hold_ids, status=Order.Status.PENDING_PAYMENT).update(status=Order.Status.EXPIRED, updated_on=now)
        for hold in holds:
            log_action(ActivityVerb.HOLD_EXPIRED, target=hold, detail={'quantity': hold.quantity})
    logger.info('holds expired', extra={'count': len(holds)})
    return len(holds)
