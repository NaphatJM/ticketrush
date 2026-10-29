from django.conf import settings
from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from db.models import BaseModel


class Event(BaseModel):
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('organizer'), on_delete=models.PROTECT, related_name='events')
    title = models.CharField(_('title'), max_length=200)
    starts_at = models.DateTimeField(_('starts at'))
    sale_opens_at = models.DateTimeField(_('sale opens at'))
    sale_closes_at = models.DateTimeField(_('sale closes at'))
    capacity = models.PositiveIntegerField(_('capacity'))
    available = models.PositiveIntegerField(_('available'))
    price_satang = models.PositiveIntegerField(_('price (satang)'))
    max_per_user = models.PositiveSmallIntegerField(_('max per user'), default=2)

    class Meta:
        verbose_name = _('event')
        verbose_name_plural = _('events')
        ordering = ('sale_opens_at', 'id')
        constraints = [
            models.CheckConstraint(condition=Q(available__gte=0) & Q(available__lte=F('capacity')), name='ck_event_available_within_capacity'),
            models.CheckConstraint(condition=Q(sale_closes_at__gt=F('sale_opens_at')), name='ck_event_sale_window_order'),
            models.CheckConstraint(condition=Q(max_per_user__gte=1), name='ck_event_max_per_user_positive'),
        ]

    def __str__(self) -> str:
        return self.title


class Hold(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = 'active'
        CONVERTED = 'converted'
        EXPIRED = 'expired'
        RELEASED = 'released'

    event = models.ForeignKey(Event, verbose_name=_('event'), on_delete=models.PROTECT, related_name='holds')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('user'), on_delete=models.PROTECT, related_name='holds')
    quantity = models.PositiveSmallIntegerField(_('quantity'))
    status = models.CharField(_('status'), max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(_('expires at'))

    class Meta:
        verbose_name = _('hold')
        verbose_name_plural = _('holds')
        ordering = ('-created_on',)
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='ck_hold_quantity_positive'),
        ]
        indexes = [
            models.Index(fields=['status', 'expires_at'], name='idx_hold_status_expiry'),
            models.Index(fields=['user', 'event', 'status'], name='idx_hold_user_event_status'),
        ]

    def __str__(self) -> str:
        return f'{self.uuid} ({self.status})'


class Order(BaseModel):
    class Status(models.TextChoices):
        PENDING_PAYMENT = 'pending_payment'
        PAID = 'paid'
        FAILED = 'failed'
        EXPIRED = 'expired'
        PAID_UNFULFILLED = 'paid_unfulfilled'

    hold = models.OneToOneField(Hold, verbose_name=_('hold'), on_delete=models.PROTECT, related_name='order')
    amount_satang = models.PositiveIntegerField(_('amount (satang)'))
    status = models.CharField(_('status'), max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    paid_at = models.DateTimeField(_('paid at'), null=True, blank=True)

    class Meta:
        verbose_name = _('order')
        verbose_name_plural = _('orders')
        ordering = ('-created_on',)

    def __str__(self) -> str:
        return f'{self.uuid} ({self.status})'
