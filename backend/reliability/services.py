import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone

from .exceptions import IdempotencyInProgress
from .exceptions import IdempotencyKeyRequired
from .exceptions import IdempotencyKeyReused
from .models import IdempotencyRecord


IDEMPOTENCY_TTL = timedelta(hours=24)
# A pending record older than this belongs to a request that died mid-flight; must exceed the longest external call.
PENDING_LEASE = timedelta(seconds=30)
_KEY_PATTERN = re.compile(r'[\x21-\x7e]{1,128}')


@dataclass(frozen=True)
class IdempotentResult:
    status_code: int
    body: Any
    replayed: bool


def request_fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def run_idempotent(*, user, key: str | None, endpoint: str, payload: Any, action: Callable[[], tuple[int, Any]]) -> IdempotentResult:
    """Run `action` at most once per (user, key, endpoint); a repeat replays the stored response.

    The record shares the action's transaction: a concurrent duplicate waits on the unique index, and a failed action leaves no record to replay.
    """
    request_hash = _validated_hash(key, payload)
    now = timezone.now()

    with transaction.atomic():
        record = _claim(user=user, key=key, endpoint=endpoint, request_hash=request_hash, now=now)
        if record.state == IdempotencyRecord.State.COMPLETE:
            return IdempotentResult(record.response_status, record.response_body, replayed=True)

        status_code, body = action()
        record.state = IdempotencyRecord.State.COMPLETE
        record.response_status = status_code
        record.response_body = body
        record.save(update_fields=['state', 'response_status', 'response_body'])
    return IdempotentResult(status_code, body, replayed=False)


def run_idempotent_two_phase[T](
    *,
    user,
    key: str | None,
    endpoint: str,
    payload: Any,
    prepare: Callable[[], T],
    perform: Callable[[T], tuple[int, Any]],
) -> IdempotentResult:
    """Like `run_idempotent`, for an action that must commit before it calls an external service.

    `prepare` commits together with a pending record, so a duplicate gets `409 in_progress` while `perform` runs outside any transaction.
    A failed `perform` deletes the record, and `prepare` must therefore resume the work it committed on an earlier attempt.
    """
    request_hash = _validated_hash(key, payload)
    now = timezone.now()

    with transaction.atomic():
        record = _claim(user=user, key=key, endpoint=endpoint, request_hash=request_hash, now=now)
        if record.state == IdempotencyRecord.State.COMPLETE:
            return IdempotentResult(record.response_status, record.response_body, replayed=True)
        prepared = prepare()

    try:
        status_code, body = perform(prepared)
    except BaseException:
        IdempotencyRecord.objects.filter(pk=record.pk, state=IdempotencyRecord.State.PENDING).delete()
        raise
    IdempotencyRecord.objects.filter(pk=record.pk).update(state=IdempotencyRecord.State.COMPLETE, response_status=status_code, response_body=body)
    return IdempotentResult(status_code, body, replayed=False)


def _validated_hash(key: str | None, payload: Any) -> str:
    if not key or not _KEY_PATTERN.fullmatch(key):
        raise IdempotencyKeyRequired
    return request_fingerprint(payload)


def _claim(*, user, key: str, endpoint: str, request_hash: str, now) -> IdempotencyRecord:
    fields = {'user': user, 'key': key, 'endpoint': endpoint}
    try:
        with transaction.atomic():
            return IdempotencyRecord.objects.create(**fields, request_hash=request_hash, expires_at=now + IDEMPOTENCY_TTL)
    except IntegrityError:
        existing = IdempotencyRecord.objects.select_for_update().get(**fields)

    stale_pending = existing.state == IdempotencyRecord.State.PENDING and existing.created_on <= now - PENDING_LEASE
    if existing.expires_at <= now or (stale_pending and existing.request_hash == request_hash):
        existing.delete()
        return IdempotencyRecord.objects.create(**fields, request_hash=request_hash, expires_at=now + IDEMPOTENCY_TTL)
    if existing.request_hash != request_hash:
        raise IdempotencyKeyReused
    if existing.state == IdempotencyRecord.State.PENDING:
        raise IdempotencyInProgress
    return existing
