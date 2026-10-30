import itertools
import os
import random
import time
import uuid
from dataclasses import dataclass

import gevent
from locust.contrib.fasthttp import FastHttpUser


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f'Set {name}; see loadtest/README.md.')
    return value


EVENT = _env('LOADTEST_EVENT')
BFF_SECRET = _env('LOADTEST_BFF_SECRET')
BUYER_PASSWORD = _env('LOADTEST_BUYER_PASSWORD')
FIRST_BUYER = int(_env('LOADTEST_FIRST_BUYER', '1'))
# Access tokens live 15 minutes; refresh a little early so no request carries an expired one.
TOKEN_REFRESH_AFTER_SECONDS = 13 * 60

_buyer_numbers = itertools.count(FIRST_BUYER)


@dataclass
class ApiResult:
    status: int
    code: str
    data: object
    headers: dict


class ApiError(Exception):
    def __init__(self, step: str, result: ApiResult):
        super().__init__(f'{step}: {result.status} {result.code}')
        self.result = result


def record(environment, kind: str, name: str, started: float, error: Exception | None = None) -> None:
    """Report a business outcome next to the HTTP stats, so Locust computes its rate and percentiles too."""
    environment.events.request.fire(
        request_type=kind,
        name=name,
        response_time=(time.perf_counter() - started) * 1000,
        response_length=0,
        exception=error,
        context={},
    )


class Buyer(FastHttpUser):
    """A mock buyer whose requests reach the API the way the Vercel BFF sends them, each with its own client IP."""

    abstract = True

    def on_start(self):
        number = next(_buyer_numbers)
        self.username = f'mock-buyer-{number:05d}'
        self.client_ip = f'10.{number >> 16 & 255}.{number >> 8 & 255}.{number & 255}'
        self.access = self.refresh = None
        self.token_issued = 0.0
        self.login()

    def headers(self, idempotency_key: str | None = None) -> dict:
        headers = {'BFF-Secret': BFF_SECRET, 'BFF-Client-IP': self.client_ip}
        if self.access:
            headers['Authorization'] = f'Bearer {self.access}'
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        return headers

    def call(self, method: str, path: str, *, name: str, json=None, key: str | None = None, ok: tuple[int, ...] = (200, 201), accept=()) -> ApiResult:
        """Send one request; statuses in `ok` and codes in `accept` count as HTTP successes, everything else as failures."""
        if self.access and time.monotonic() - self.token_issued > TOKEN_REFRESH_AFTER_SECONDS:
            self.renew()
        with self.client.request(method, path, name=name, json=json, headers=self.headers(key), catch_response=True) as response:
            result = _parse(response)
            if result.status in ok or result.code in accept:
                response.success()
            else:
                response.failure(f'{result.status} {result.code}')
        return result

    def login(self) -> None:
        self.access = None
        result = self.call('POST', '/api/auth/login/', name='auth: login', json={'username': self.username, 'password': BUYER_PASSWORD})
        if result.status != 200:
            raise ApiError('login', result)
        self._store_tokens(result.data)

    def renew(self) -> None:
        refresh, self.access = self.refresh, None
        result = self.call('POST', '/api/auth/refresh/', name='auth: refresh', json={'refresh': refresh})
        if result.status != 200:
            self.login()
            return
        self._store_tokens(result.data)

    def _store_tokens(self, data: dict) -> None:
        self.access, self.refresh = data['access'], data['refresh']
        self.token_issued = time.monotonic()

    def hold(self, quantity: int, *, name: str = 'hold: create', key: str | None = None, accept=()) -> ApiResult:
        return self.call('POST', f'/api/events/{EVENT}/holds/', name=name, json={'quantity': quantity}, key=key or new_key(), accept=accept)


def _parse(response) -> ApiResult:
    try:
        body = response.json()
    except Exception:
        body = None
    headers = {name.lower(): value for name, value in (response.headers or {}).items()}
    if not isinstance(body, dict):
        return ApiResult(response.status_code or 0, 'NO_JSON' if response.status_code else 'CONNECTION_ERROR', None, headers)
    return ApiResult(response.status_code, body.get('status', {}).get('code', ''), body.get('data'), headers)


def new_key() -> str:
    return str(uuid.uuid4())


def think(low: float = 1.0, high: float = 3.0) -> None:
    gevent.sleep(random.uniform(low, high))  # noqa: S311
