import secrets
import time
import uuid


_UUID7_VERSION = 7
_UUID_VARIANT_RFC4122 = 2


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: time-ordered, so new rows append to the end of the unique index."""
    timestamp_ms = (time.time_ns() // 1_000_000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (_UUID7_VERSION << 76) | (rand_a << 64) | (_UUID_VARIANT_RFC4122 << 62) | rand_b
    return uuid.UUID(int=value)
