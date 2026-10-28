from typing import Any

from django_guid import get_guid

from audit.constants import ActivityVerb
from audit.middleware import get_client_ip
from audit.models import ActivityLog


_MAX_CID = ActivityLog._meta.get_field('cid').max_length
_MAX_USERNAME = ActivityLog._meta.get_field('actor_username').max_length
_MAX_TARGET_ID = ActivityLog._meta.get_field('target_id').max_length
_MAX_IP = ActivityLog._meta.get_field('ip_address').max_length


def log_action(verb: ActivityVerb, *, actor=None, target=None, detail: dict[str, Any] | None = None) -> ActivityLog:
    """Write one audit row. Call inside the service's transaction so the row commits or rolls back with the change."""
    return ActivityLog.objects.create(
        verb=str(verb),
        actor=actor if getattr(actor, 'pk', None) else None,
        actor_username=(getattr(actor, 'username', '') or '')[:_MAX_USERNAME],
        target_label=target._meta.label if target is not None else '',
        target_id=(str(getattr(target, 'uuid', None) or target.pk) if target is not None else '')[:_MAX_TARGET_ID],
        cid=(get_guid() or '')[:_MAX_CID],
        ip_address=get_client_ip()[:_MAX_IP],
        detail=detail or {},
    )
