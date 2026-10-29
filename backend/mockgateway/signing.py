import hashlib
import hmac
import time


SIGNATURE_HEADER = 'Mock-Signature'
#: Bounds how long a captured request can be replayed.
TOLERANCE_SECONDS = 300


class InvalidSignatureError(Exception):
    pass


def sign(body: bytes, *, secret: str, timestamp: int | None = None) -> str:
    timestamp = int(time.time()) if timestamp is None else timestamp
    return f't={timestamp},v1={_digest(body, secret=secret, timestamp=timestamp)}'


def verify(body: bytes, header: str | None, *, secret: str, now: int | None = None) -> None:
    if not secret:
        raise InvalidSignatureError('no webhook secret is configured')
    try:
        parts = dict(item.split('=', 1) for item in (header or '').split(','))
        timestamp = int(parts['t'])
        signature = parts['v1']
    except (KeyError, ValueError) as exc:
        raise InvalidSignatureError('malformed signature header') from exc

    now = int(time.time()) if now is None else now
    if abs(now - timestamp) > TOLERANCE_SECONDS:
        raise InvalidSignatureError('timestamp outside the tolerance')
    if not hmac.compare_digest(signature, _digest(body, secret=secret, timestamp=timestamp)):
        raise InvalidSignatureError('signature mismatch')


def _digest(body: bytes, *, secret: str, timestamp: int) -> str:
    return hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
