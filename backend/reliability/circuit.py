import threading
import time
from collections.abc import Callable


class CircuitBreaker:
    """Stops calling a failing dependency for `reset_after_seconds`, then lets one trial call through.

    State is per process: each gunicorn worker trips on its own, so the breaker needs no shared store that could itself be down.
    """

    def __init__(self, *, failure_threshold: int, reset_after_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_running = False

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return 'closed'
            return 'open' if self._clock() - self._opened_at < self.reset_after_seconds else 'half_open'

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.reset_after_seconds or self._trial_running:
                return False
            self._trial_running = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_running = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._trial_running = False
            if self._opened_at is not None or self._failures >= self.failure_threshold:
                self._opened_at = self._clock()
