from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .constants import ActivityVerb


class ActivityLog(models.Model):
    """Append-only business audit trail: who changed what, when, and from where."""

    verb = models.CharField(_('verb'), max_length=50, choices=ActivityVerb.choices, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_('actor'),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
    )
    actor_username = models.CharField(_('actor username'), max_length=150, blank=True, default='')
    target_label = models.CharField(_('target label'), max_length=100, blank=True, default='')
    target_id = models.CharField(_('target id'), max_length=64, blank=True, default='', db_index=True)
    cid = models.CharField(_('correlation id'), max_length=100, blank=True, default='', db_index=True)
    ip_address = models.CharField(_('ip address'), max_length=45, blank=True, default='')
    detail = models.JSONField(_('detail'), default=dict, blank=True, help_text=_('Never store passwords, tokens, or payment data.'))
    created_on = models.DateTimeField(_('created on'), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('activity log')
        verbose_name_plural = _('activity logs')
        ordering = ('-created_on',)
        indexes = [
            models.Index(fields=['target_label', 'target_id'], name='idx_activity_target'),
            models.Index(fields=['actor', '-created_on'], name='idx_activity_actor_time'),
        ]

    def __str__(self) -> str:
        return f'{self.created_on:%Y-%m-%d %H:%M} {self.verb} {self.actor_username or "-"}'
