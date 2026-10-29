from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.db.models import F
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from db.models import BaseModel


https_only = URLValidator(schemes=['https'])


class Event(BaseModel):
    class Category(models.TextChoices):
        CONCERT = 'concert', _('Concert')
        FESTIVAL = 'festival', _('Festival')
        THEATRE = 'theatre', _('Theatre')
        COMEDY = 'comedy', _('Comedy')
        SPORTS = 'sports', _('Sports')
        CONFERENCE = 'conference', _('Conference')
        WORKSHOP = 'workshop', _('Workshop')
        OTHER = 'other', _('Other')

    class SaleStatus(models.TextChoices):
        UPCOMING = 'upcoming'
        ON_SALE = 'on_sale'
        SOLD_OUT = 'sold_out'
        CLOSED = 'closed'

    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('organizer'), on_delete=models.PROTECT, related_name='events')
    title = models.CharField(_('title'), max_length=200)
    summary = models.CharField(_('summary'), max_length=280, blank=True)
    description = models.TextField(_('description'), blank=True, help_text=_('Plain text; line breaks are kept.'))
    important_info = models.TextField(_('important info'), blank=True, help_text=_('Entry rules and notes; also printed in the ticket email.'))
    category = models.CharField(_('category'), max_length=16, choices=Category.choices, default=Category.OTHER)
    presented_by = models.CharField(_('presented by'), max_length=120, blank=True)
    banner_url = models.URLField(_('banner URL'), max_length=500, blank=True, validators=[https_only])
    venue_name = models.CharField(_('venue name'), max_length=200, blank=True)
    venue_address = models.CharField(_('venue address'), max_length=300, blank=True)
    venue_map_url = models.URLField(_('venue map URL'), max_length=500, blank=True, validators=[https_only])
    is_published = models.BooleanField(_('published'), default=False, help_text=_('Unpublished events are hidden from the API and cannot be held.'))
    starts_at = models.DateTimeField(_('starts at'))
    ends_at = models.DateTimeField(_('ends at'), null=True, blank=True)
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
            models.CheckConstraint(condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F('starts_at')), name='ck_event_ends_after_start'),
        ]

    def __str__(self) -> str:
        return self.title

    def sale_status(self, now) -> str:
        if now >= self.sale_closes_at:
            return self.SaleStatus.CLOSED
        if now < self.sale_opens_at:
            return self.SaleStatus.UPCOMING
        if self.available == 0:
            return self.SaleStatus.SOLD_OUT
        return self.SaleStatus.ON_SALE

    @classmethod
    def sale_status_filter(cls, status: str, now) -> Q:
        return {
            cls.SaleStatus.CLOSED: Q(sale_closes_at__lte=now),
            cls.SaleStatus.UPCOMING: Q(sale_opens_at__gt=now, sale_closes_at__gt=now),
            cls.SaleStatus.SOLD_OUT: Q(sale_opens_at__lte=now, sale_closes_at__gt=now, available=0),
            cls.SaleStatus.ON_SALE: Q(sale_opens_at__lte=now, sale_closes_at__gt=now, available__gt=0),
        }[status]


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
