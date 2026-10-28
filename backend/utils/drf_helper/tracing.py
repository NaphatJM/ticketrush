import functools
import logging
import time
from collections.abc import Callable
from typing import Any


def traced[F: Callable[..., Any]](func: F) -> F:
    """Log entry and exit with duration at DEBUG; costs one level check when DEBUG is off."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        if not logger.isEnabledFor(logging.DEBUG):
            return func(*args, **kwargs)
        logger.debug('enter %s', func.__qualname__)
        started = time.perf_counter()
        result = func(*args, **kwargs)
        logger.debug('exit %s', func.__qualname__, extra={'duration_ms': round((time.perf_counter() - started) * 1000, 1)})
        return result

    return wrapper  # type: ignore[return-value]
