import json
import urllib.error
import urllib.request
from typing import Any


API_URL = 'https://api.resend.com/emails'
TIMEOUT_SECONDS = 10

# A 409 with one of these names means the same key is still being processed; any other 409 means the body changed.
_RETRYABLE_CONFLICTS = frozenset({'concurrent_idempotent_requests', 'resource_locked'})
# These 429s last until the quota resets, far beyond the retry window.
_QUOTA_ERRORS = frozenset({'daily_quota_exceeded', 'monthly_quota_exceeded'})


class EmailRejectedError(Exception):
    """Resend refused the message itself, so sending it again cannot succeed."""


class EmailUnavailableError(Exception):
    pass


def send_email(*, api_key: str, message: dict[str, Any], idempotency_key: str) -> str:
    """Send one email and return its Resend ID. A repeat with the same key and body within 24 hours sends nothing new."""
    request = urllib.request.Request(  # noqa: S310
        API_URL,
        data=json.dumps(message, separators=(',', ':')).encode(),
        method='POST',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Idempotency-Key': idempotency_key,
            'User-Agent': 'ticketrush',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.load(response)['id']
    except urllib.error.HTTPError as exc:
        error = _error_name(exc)
        detail = f'Resend {exc.code} {error}'
        if (exc.code == 429 and error not in _QUOTA_ERRORS) or exc.code >= 500 or (exc.code == 409 and error in _RETRYABLE_CONFLICTS):
            raise EmailUnavailableError(detail) from exc
        raise EmailRejectedError(detail) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EmailUnavailableError(f'Resend unreachable: {exc}') from exc


def _error_name(exc: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(exc.read()).get('name', ''))
    except (ValueError, AttributeError, OSError):
        return ''
