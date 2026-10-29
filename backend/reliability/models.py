from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class IdempotencyRecord(models.Model):
    class State(models.TextChoices):
        PENDING = 'pending'
        COMPLETE = 'complete'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_('user'), on_delete=models.CASCADE, related_name='+')
    key = models.CharField(_('key'), max_length=128)
    endpoint = models.CharField(_('endpoint'), max_length=64)
    state = models.CharField(_('state'), max_length=16, choices=State.choices, default=State.PENDING)
    request_hash = models.CharField(_('request hash'), max_length=64)
    response_status = models.PositiveSmallIntegerField(_('response status'), null=True, blank=True)
    response_body = models.JSONField(_('response body'), null=True, blank=True)
    created_on = models.DateTimeField(_('created on'), auto_now_add=True)
    expires_at = models.DateTimeField(_('expires at'), db_index=True)

    class Meta:
        verbose_name = _('idempotency record')
        verbose_name_plural = _('idempotency records')
        constraints = [
            models.UniqueConstraint(fields=['user', 'key', 'endpoint'], name='uq_idempotency_user_key_endpoint'),
        ]

    def __str__(self) -> str:
        return f'{self.endpoint} {self.key} ({self.state})'
