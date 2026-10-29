from django.db import models
from django.utils.translation import gettext_lazy as _

from db.models import BaseModel
from ticketing.models import Order


class Payment(BaseModel):
    class Status(models.TextChoices):
        CREATED = 'created'
        PENDING = 'pending'
        SUCCEEDED = 'succeeded'
        FAILED = 'failed'

    order = models.ForeignKey(Order, verbose_name=_('order'), on_delete=models.PROTECT, related_name='payments')
    provider = models.CharField(_('provider'), max_length=32)
    provider_charge_id = models.CharField(_('provider charge id'), max_length=64, unique=True, null=True, blank=True)
    payment_url = models.URLField(_('payment URL'), max_length=500, blank=True)
    status = models.CharField(_('status'), max_length=16, choices=Status.choices, default=Status.CREATED)
    amount_satang = models.PositiveIntegerField(_('amount (satang)'))
    expires_at = models.DateTimeField(_('expires at'))

    class Meta:
        verbose_name = _('payment')
        verbose_name_plural = _('payments')
        ordering = ('-created_on',)

    def __str__(self) -> str:
        return f'{self.uuid} ({self.status})'


class WebhookEvent(models.Model):
    provider = models.CharField(_('provider'), max_length=32)
    provider_event_id = models.CharField(_('provider event id'), max_length=100)
    event_type = models.CharField(_('event type'), max_length=64)
    payment_key = models.CharField(_('payment key'), max_length=128)
    payload = models.JSONField(_('payload'))
    received_at = models.DateTimeField(_('received at'), auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(_('processed at'), null=True, blank=True)

    class Meta:
        verbose_name = _('webhook event')
        verbose_name_plural = _('webhook events')
        ordering = ('-received_at',)
        constraints = [
            models.UniqueConstraint(fields=['provider', 'provider_event_id'], name='uq_webhook_provider_event'),
        ]

    def __str__(self) -> str:
        return f'{self.provider} {self.provider_event_id}'


class Ticket(BaseModel):
    order = models.ForeignKey(Order, verbose_name=_('order'), on_delete=models.PROTECT, related_name='tickets')
    seq = models.PositiveSmallIntegerField(_('sequence'))
    code = models.CharField(_('code'), max_length=200, unique=True)
    issued_at = models.DateTimeField(_('issued at'), auto_now_add=True)

    class Meta:
        verbose_name = _('ticket')
        verbose_name_plural = _('tickets')
        ordering = ('order', 'seq')
        constraints = [
            models.UniqueConstraint(fields=['order', 'seq'], name='uq_ticket_order_seq'),
        ]

    def __str__(self) -> str:
        return f'{self.order_id}-{self.seq}'
