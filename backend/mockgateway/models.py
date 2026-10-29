import secrets

from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from db.models import BaseModel


_RATE_VALIDATORS = [MinValueValidator(0.0), MaxValueValidator(1.0)]


def new_charge_id() -> str:
    return f'chrg_mock_{secrets.token_hex(12)}'


class FaultConfig(BaseModel):
    """Fault injection for demos and load tests; one row, edited in the admin."""

    latency_ms = models.PositiveIntegerField(_('charge latency (ms)'), default=0)
    error_rate = models.FloatField(_('charge error rate'), default=0.0, validators=_RATE_VALIDATORS)
    duplicate_webhook_rate = models.FloatField(_('duplicate webhook rate'), default=0.0, validators=_RATE_VALIDATORS)
    drop_webhook_rate = models.FloatField(_('dropped webhook rate'), default=0.0, validators=_RATE_VALIDATORS)

    class Meta:
        verbose_name = _('fault config')
        verbose_name_plural = _('fault config')

    def __str__(self) -> str:
        return 'Fault config'

    @classmethod
    def load(cls) -> 'FaultConfig':
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class MockCharge(BaseModel):
    class Status(models.TextChoices):
        PENDING = 'pending'
        SUCCEEDED = 'succeeded'
        FAILED = 'failed'
        EXPIRED = 'expired'

    charge_id = models.CharField(_('charge id'), max_length=40, unique=True, default=new_charge_id)
    idempotency_key = models.CharField(_('idempotency key'), max_length=128, unique=True)
    amount_satang = models.PositiveIntegerField(_('amount (satang)'))
    status = models.CharField(_('status'), max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField(_('expires at'))

    class Meta:
        verbose_name = _('mock charge')
        verbose_name_plural = _('mock charges')
        ordering = ('-created_on',)

    def __str__(self) -> str:
        return f'{self.charge_id} ({self.status})'
