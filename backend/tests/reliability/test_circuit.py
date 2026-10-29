from reliability.circuit import CircuitBreaker


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _breaker(clock):
    return CircuitBreaker(failure_threshold=3, reset_after_seconds=30, clock=clock)


def test_the_circuit_opens_after_the_failure_threshold():
    clock = FakeClock()
    breaker = _breaker(clock)

    for _ in range(3):
        assert breaker.allow()
        breaker.record_failure()

    assert breaker.state == 'open'
    assert not breaker.allow()


def test_a_success_resets_the_failure_count():
    breaker = _breaker(FakeClock())
    breaker.record_failure()
    breaker.record_failure()

    breaker.record_success()
    breaker.record_failure()

    assert breaker.state == 'closed'


def test_after_the_reset_period_only_one_trial_call_goes_through():
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()

    clock.now = 31

    assert breaker.state == 'half_open'
    assert breaker.allow()
    assert not breaker.allow()


def test_a_successful_trial_closes_the_circuit():
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now = 31
    breaker.allow()

    breaker.record_success()

    assert breaker.state == 'closed'
    assert breaker.allow()


def test_a_failed_trial_opens_the_circuit_again():
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now = 31
    breaker.allow()

    breaker.record_failure()

    assert breaker.state == 'open'
    assert not breaker.allow()
