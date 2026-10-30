"""Flash sale: buyers sign in, refresh the event page until the sale opens, then each tries to hold one ticket at once."""

import json
import os
import random
import time
from datetime import datetime

import gevent
from locust import events
from locust import task
from locust.exception import StopUser

from common import EVENT
from common import ApiError
from common import Buyer
from common import record

# Real fans click within about a second of the sale opening, not all in the same millisecond.
CLICK_SPREAD_SECONDS = float(os.environ.get('LOADTEST_CLICK_SPREAD_SECONDS', '1.0'))
SALE_NOT_OPEN_RETRIES = 20

started_buyers = 0
outcomes = {'won': 0, 'sold_out': 0, 'error': 0}
win_offsets: list[float] = []
sale: dict = {}


class FlashSaleBuyer(Buyer):
    def on_start(self):
        global started_buyers
        started_buyers += 1
        started = time.perf_counter()
        try:
            super().on_start()
            if not sale:
                detail = self._expect_event()
                sale.update(opens_at=datetime.fromisoformat(detail['sale_opens_at']).timestamp(), capacity=detail['capacity'])
        except Exception as error:
            outcomes['error'] += 1
            record(self.environment, 'OUTCOME', 'start error', started, error)
            raise StopUser() from error

    def _expect_event(self) -> dict:
        result = self.call('GET', f'/api/events/{EVENT}/', name='event: detail')
        if result.status != 200:
            raise ApiError('event: detail', result)
        return result.data

    @task
    def buy_one_ticket(self):
        opens_at = sale['opens_at']
        while (remaining := opens_at - time.time()) > 0:
            gevent.sleep(min(remaining, random.uniform(2, 5)))  # noqa: S311
            if opens_at - time.time() > 0:
                self.call('GET', f'/api/events/{EVENT}/', name='event: detail')
        gevent.sleep(random.uniform(0, CLICK_SPREAD_SECONDS))  # noqa: S311

        started = time.perf_counter()
        result = self._hold()
        if result.status == 201:
            outcomes['won'] += 1
            win_offsets.append(time.time() - opens_at)
            record(self.environment, 'OUTCOME', 'hold won', started)
        elif result.code == 'SOLD_OUT':
            outcomes['sold_out'] += 1
            record(self.environment, 'OUTCOME', 'hold sold out', started)
        else:
            outcomes['error'] += 1
            record(self.environment, 'OUTCOME', 'hold error', started, RuntimeError(f'{result.status} {result.code}'))
        raise StopUser()

    def _hold(self):
        """Sold out is the expected answer for most buyers; a clock a little ahead of the server's gets SALE_NOT_OPEN briefly."""
        for _ in range(SALE_NOT_OPEN_RETRIES):
            result = self.hold(1, accept=('SOLD_OUT', 'SALE_NOT_OPEN'))
            if result.code == 'SALE_NOT_OPEN':
                gevent.sleep(0.25)
            elif result.code == 'THROTTLED':
                gevent.sleep(float(result.headers.get('retry-after') or 1))
            else:
                return result
        return result


@events.test_stop.add_listener
def _summarize(environment, **kwargs):
    capacity = sale.get('capacity')
    summary = {
        'event': EVENT,
        'capacity': capacity,
        'buyers_started': started_buyers,
        'buyers_finished': sum(outcomes.values()),
        'outcomes': outcomes,
        'oversold': capacity is not None and outcomes['won'] > capacity,
        'first_win_after_open_s': round(min(win_offsets), 3) if win_offsets else None,
        'sold_out_after_open_s': round(max(win_offsets), 3) if win_offsets and outcomes['won'] == capacity else None,
    }
    text = json.dumps(summary, indent=2)
    print(text)
    if path := os.environ.get('LOADTEST_SUMMARY'):
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
