"""Weighted buyer journeys; each is recorded as a JOURNEY entry, and `time to ticket` runs from the hold click to My tickets."""

import os
import random
import time

import gevent
from locust import between
from locust import task

from common import EVENT
from common import ApiError
from common import ApiResult
from common import Buyer
from common import new_key
from common import record
from common import think

PAY_TIMEOUT_SECONDS = float(os.environ.get('LOADTEST_PAY_TIMEOUT_SECONDS', '60'))
# Share of holds and checkouts sent twice with the same Idempotency-Key, as a client does after a lost response.
REPLAY_RATE = float(os.environ.get('LOADTEST_REPLAY_RATE', '0'))


def poll_delay_seconds(attempt: int) -> float:
    """Same backoff as the order page: 1.5 s, then 3 s, then 5 s."""
    if attempt < 4:
        return 1.5
    if attempt < 8:
        return 3.0
    return 5.0


class JourneyBuyer(Buyer):
    wait_time = between(1, 5)

    @task(60)
    def buy(self):
        self._journey('buy', self._buy, decline_first=False)

    @task(15)
    def buy_after_decline(self):
        self._journey('buy after decline', self._buy, decline_first=True)

    @task(10)
    def release(self):
        self._journey('release', self._release)

    @task(10)
    def abandon(self):
        self._journey('abandon', self._abandon)

    @task(5)
    def browse(self):
        self._journey('browse', self._browse)

    def _journey(self, name: str, steps, **kwargs) -> None:
        started = time.perf_counter()
        try:
            steps(**kwargs)
        except Exception as error:
            record(self.environment, 'JOURNEY', name, started, error)
        else:
            record(self.environment, 'JOURNEY', name, started)

    def _browse(self) -> None:
        self._open_list()
        think()
        self._open_event()
        think()
        self._open_list()

    def _buy(self, *, decline_first: bool) -> None:
        self._open_list()
        think()
        self._open_event()
        think()
        clicked = time.perf_counter()
        hold = self._hold(random.choice((1, 2)))  # noqa: S311
        order = self._checkout(hold['uuid'])
        think()
        if decline_first:
            self._pay(order, outcome='failed')
            self._wait_for(order['uuid'], 'failed')
            think()
            order = self._checkout(hold['uuid'])
        self._pay(order, outcome='succeeded')
        self._wait_for(order['uuid'], 'paid')
        self._expect('tickets: mine', self.call('GET', '/api/me/tickets/', name='tickets: mine'))
        record(self.environment, 'JOURNEY', 'time to ticket', clicked)

    def _release(self) -> None:
        self._open_event()
        think()
        hold = self._hold(1)
        think()
        self._expect('hold: release', self.call('DELETE', f'/api/holds/{hold["uuid"]}/', name='hold: release'))

    def _abandon(self) -> None:
        self._open_event()
        think()
        hold = self._hold(1)
        if random.random() < 0.5:  # noqa: S311
            think()
            self._checkout(hold['uuid'])

    def _open_list(self) -> None:
        query = random.choice(('', '?status=on_sale', '?category=other'))  # noqa: S311
        self._expect('events: list', self.call('GET', f'/api/events/{query}', name='events: list'))

    def _open_event(self) -> None:
        self._expect('event: detail', self.call('GET', f'/api/events/{EVENT}/', name='event: detail'))

    def _hold(self, quantity: int) -> dict:
        key = new_key()
        hold = self._expect('hold', self.hold(quantity, key=key))
        if random.random() < REPLAY_RATE:  # noqa: S311
            self._replay_hold(quantity, key, hold)
        return hold

    def _replay_hold(self, quantity: int, key: str, original: dict) -> None:
        started = time.perf_counter()
        result = self.hold(quantity, name='hold: replay', key=key)
        replayed = result.status == 201 and result.headers.get('idempotent-replayed') == 'true' and result.data['uuid'] == original['uuid']
        record(self.environment, 'REPLAY', 'hold sequential', started, None if replayed else RuntimeError(f'{result.status} {result.code}'))

    def _checkout(self, hold_uuid: str) -> dict:
        key = new_key()
        path = f'/api/holds/{hold_uuid}/checkout/'
        if random.random() >= REPLAY_RATE:  # noqa: S311
            return self._expect('checkout', self.call('POST', path, name='checkout', key=key))

        # Two copies at once: one runs, the other waits on IN_PROGRESS or replays the stored result; never two charges.
        started = time.perf_counter()
        first = gevent.spawn(self.call, 'POST', path, name='checkout', key=key, accept=('IN_PROGRESS',))
        second = gevent.spawn(self.call, 'POST', path, name='checkout: replay', key=key, accept=('IN_PROGRESS',))
        gevent.joinall((first, second))
        results = [first.value, second.value]
        created = [result for result in results if result.status == 201]
        consistent = created and all(
            result.code == 'IN_PROGRESS' or (result.status == 201 and result.data['uuid'] == created[0].data['uuid']) for result in results
        )
        record(self.environment, 'REPLAY', 'checkout concurrent', started, None if consistent else RuntimeError(str([r.code for r in results])))
        if not created:
            raise ApiError('checkout', first.value)
        return created[0].data

    def _pay(self, order: dict, *, outcome: str) -> None:
        charge_id = order['payment']['payment_url'].rstrip('/').rsplit('/', 1)[-1]
        self._expect('gateway: page', self.call('GET', f'/mock-gateway/charges/{charge_id}/', name='gateway: page'))
        self._expect('gateway: pay', self.call('POST', f'/mock-gateway/charges/{charge_id}/pay/', name='gateway: pay', json={'outcome': outcome}))

    def _wait_for(self, order_uuid: str, status: str) -> None:
        """Poll as the order page does; the webhook task pays the order and issues its tickets in the background."""
        deadline = time.monotonic() + PAY_TIMEOUT_SECONDS
        attempt = 0
        while True:
            order = self._expect('order: poll', self.call('GET', f'/api/orders/{order_uuid}/', name='order: poll'))
            if order['status'] == status:
                return
            if time.monotonic() > deadline:
                raise ApiError(f'order still {order["status"]}, wanted {status}', ApiResult(0, 'TIMEOUT', order, {}))
            gevent.sleep(poll_delay_seconds(attempt))
            attempt += 1

    @staticmethod
    def _expect(step: str, result) -> dict:
        if result.status not in (200, 201):
            raise ApiError(step, result)
        return result.data
