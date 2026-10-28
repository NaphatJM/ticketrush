from django.conf import settings
from django.db import models
from django.utils import timezone


class APIRequestLog(models.Model):
    """One row per tracked API request; joins logs and audit rows through `cid`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    username_persistent = models.CharField(max_length=150, blank=True, default='')
    requested_at = models.DateTimeField(default=timezone.now, db_index=True)
    response_ms = models.PositiveIntegerField(default=0)
    path = models.CharField(max_length=200, db_index=True)
    view = models.CharField(max_length=200, blank=True, default='', db_index=True)
    method = models.CharField(max_length=10)
    status_code = models.PositiveSmallIntegerField(db_index=True)
    remote_addr = models.CharField(max_length=45, blank=True, default='')
    host = models.CharField(max_length=255, blank=True, default='')
    user_agent = models.CharField(max_length=255, blank=True, default='')
    query_params = models.JSONField(default=dict, blank=True)
    data = models.JSONField(null=True, blank=True)
    response = models.JSONField(null=True, blank=True, help_text='Stored for error responses only.')
    errors = models.TextField(blank=True, default='')
    cid = models.CharField(max_length=100, blank=True, default='', db_index=True)

    class Meta:
        verbose_name = 'API request log'
        ordering = ('-requested_at',)

    def __str__(self) -> str:
        return f'{self.method} {self.path} {self.status_code}'
