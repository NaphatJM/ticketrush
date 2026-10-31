"""Races run on real threads and connections; each test commits, so the database is flushed afterwards."""

import threading
from collections import Counter
from unittest import mock

import pytest

from accounts import services
from accounts.models import User
from tests.concurrency import outcome
from tests.concurrency import race


pytestmark = pytest.mark.django_db(transaction=True)

PASSWORD = 'correct-horse-battery-7'


def test_simultaneous_sign_ups_with_one_email_create_one_account():
    emails = ['alice@example.com', 'ALICE@example.com', 'Alice@Example.com', 'alice@EXAMPLE.COM'] * 2

    results = race(
        [lambda n=n, email=email: services.register_user(username=f'alice-{n}', email=email, password=PASSWORD) for n, email in enumerate(emails)]
    )

    assert Counter(map(outcome, results)) == {'ok': 1, 'EmailTaken': 7}
    assert User.objects.filter(email__iexact='alice@example.com').count() == 1


def test_a_sign_up_that_passed_the_email_check_still_loses_to_the_index():
    """Both sign-ups see the email free before either inserts, which only the unique index can settle."""
    both_checked = threading.Barrier(2, timeout=5)
    check = services.email_in_use
    calls = Counter()
    lock = threading.Lock()

    def check_then_wait(email):
        in_use = check(email)
        with lock:
            calls['n'] += 1
            first_two = calls['n'] <= 2
        if first_two:
            both_checked.wait()
        return in_use

    with mock.patch.object(services, 'email_in_use', side_effect=check_then_wait):
        results = race(
            [
                lambda: services.register_user(username='alice', email='alice@example.com', password=PASSWORD),
                lambda: services.register_user(username='alicia', email='Alice@example.com', password=PASSWORD),
            ]
        )

    assert Counter(map(outcome, results)) == {'ok': 1, 'EmailTaken': 1}
    assert User.objects.filter(email__iexact='alice@example.com').count() == 1
