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


class OutboxMessage(models.Model):
    """A Celery task to enqueue once the transaction that wrote it commits; `topic` is the task name and `payload` its kwargs."""

    topic = models.CharField(_('topic'), max_length=100)
    payload = models.JSONField(_('payload'), default=dict)
    created_on = models.DateTimeField(_('created on'), auto_now_add=True)
    published_at = models.DateTimeField(_('published at'), null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(_('attempts'), default=0)
    last_error = models.TextField(_('last error'), blank=True)

    class Meta:
        verbose_name = _('outbox message')
        verbose_name_plural = _('outbox messages')
        indexes = [
            models.Index(fields=['id'], condition=models.Q(published_at__isnull=True), name='idx_outbox_unpublished'),
        ]

    def __str__(self) -> str:
        return f'{self.topic} #{self.pk}'


class DeadLetter(models.Model):
    task_name = models.CharField(_('task name'), max_length=100)
    args = models.JSONField(_('args'), default=dict)
    error = models.TextField(_('error'))
    failed_at = models.DateTimeField(_('failed at'), auto_now_add=True, db_index=True)
    replayed_at = models.DateTimeField(_('replayed at'), null=True, blank=True)

    class Meta:
        verbose_name = _('dead letter')
        verbose_name_plural = _('dead letters')
        ordering = ('-failed_at',)

    def __str__(self) -> str:
        return f'{self.task_name} at {self.failed_at:%Y-%m-%d %H:%M:%S}'
