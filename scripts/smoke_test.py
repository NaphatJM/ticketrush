"""Buy one ticket end to end against a live API: register, hold, replay the hold key, check out, pay through the mock gateway, wait for the ticket.

Every run creates a user and a paid one-ticket order, which takes a seat from the chosen event. Exits 1 on the first failed step.
"""

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--api', default='https://api.ticketrush.naphat.online', help='API base URL')
    parser.add_argument('--event', help='event UUID; default: the on-sale event with the most seats left')
    parser.add_argument('--email', default='delivered@resend.dev', help="buyer email; the default is Resend's test inbox")
    parser.add_argument('--paid-timeout', type=float, default=60, help='seconds to wait for the order to turn paid')
    args = parser.parse_args()
    smoke = Smoke(args.api.rstrip('/'))
    try:
        smoke.run(event_uuid=args.event, email=args.email, paid_timeout=args.paid_timeout)
    except StepFailedError:
        return 1
    finally:
        print(f'\n{smoke.passed}/{smoke.steps} steps passed')
    return 0


class StepFailedError(Exception):
    pass


class Smoke:
    def __init__(self, api: str):
        self.api = api
        self.token: str | None = None
        self.steps = 0
        self.passed = 0

    def run(self, *, event_uuid: str | None, email: str, paid_timeout: float) -> None:
        status, payload, _, elapsed = self.call('GET', '/system/readiness/')
        self.check('readiness', status == 200, f'{status} in {elapsed:.2f}s {payload.get("error", "")}')

        event = self.pick_event(event_uuid)
        print(f'      event: {event["title"]} ({event["uuid"]}), {event["available"]} left')

        username = f'smoke{int(time.time())}'
        status, payload, _, elapsed = self.call(
            'POST', '/api/auth/register/', body={'username': username, 'email': email, 'password': secrets.token_urlsafe(16)}
        )
        self.check('register', status == 201, f'{status} {username} in {elapsed:.2f}s')
        self.token = payload['data']['access']

        key = str(uuid.uuid4())
        path = f'/api/events/{event["uuid"]}/holds/'
        status, payload, _, elapsed = self.call('POST', path, body={'quantity': 1}, key=key)
        self.check('hold', status == 201, f'{status} in {elapsed:.2f}s')
        hold = payload['data']
        status, payload, headers, _ = self.call('POST', path, body={'quantity': 1}, key=key)
        replayed = headers.get('Idempotent-Replayed')
        self.check('hold key replay', status == 201 and payload['data']['uuid'] == hold['uuid'] and replayed == 'true', f'replayed={replayed}')

        status, payload, _, elapsed = self.call('POST', f'/api/holds/{hold["uuid"]}/checkout/', body={}, key=str(uuid.uuid4()))
        self.check('checkout', status in (200, 201), f'{status} in {elapsed:.2f}s')
        order = payload['data']
        charge_id = order['payment']['payment_url'].rstrip('/').rsplit('/', 1)[-1]
        print(f'      order {order["uuid"]}, charge {charge_id}')

        status, _, _, elapsed = self.call('GET', f'/mock-gateway/charges/{charge_id}/')
        self.check('gateway page', status == 200, f'{status} in {elapsed:.2f}s')
        status, _, _, elapsed = self.call('POST', f'/mock-gateway/charges/{charge_id}/pay/', body={'outcome': 'succeeded'})
        self.check('gateway pay', status == 200, f'{status} in {elapsed:.2f}s')

        paid_from = time.monotonic()
        order_status = None
        while time.monotonic() - paid_from < paid_timeout:
            _, payload, _, _ = self.call('GET', f'/api/orders/{order["uuid"]}/')
            order_status = payload.get('data', {}).get('status')
            if order_status == 'paid':
                break
            time.sleep(1)
        self.check('order paid', order_status == 'paid', f'status={order_status} after {time.monotonic() - paid_from:.1f}s')

        status, payload, _, _ = self.call('GET', '/api/me/tickets/')
        tickets = payload.get('data', [])
        self.check('my tickets', status == 200 and len(tickets) == 1, f'{status}, {len(tickets)} ticket(s)')

    def pick_event(self, event_uuid: str | None) -> dict:
        if event_uuid:
            status, payload, _, _ = self.call('GET', f'/api/events/{event_uuid}/')
            event = payload.get('data') or {}
            self.check('event on sale', status == 200 and event.get('sale_status') == 'on_sale' and event.get('available', 0) >= 1, f'{status}')
            return event
        status, payload, _, _ = self.call('GET', '/api/events/?status=on_sale&page_size=200')
        events = [event for event in payload.get('data', []) if event['sale_status'] == 'on_sale' and event['available'] >= 1]
        self.check('event on sale', status == 200 and bool(events), f'{status}, {len(events)} with seats left')
        return max(events, key=lambda event: event['available'])

    def call(self, method: str, path: str, *, body: dict | None = None, key: str | None = None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        if key:
            headers['Idempotency-Key'] = key
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.api + path, data=data, method=method, headers=headers)  # noqa: S310
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                status, raw, response_headers = response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            status, raw, response_headers = exc.code, exc.read(), exc.headers
        except (urllib.error.URLError, TimeoutError) as exc:
            return 0, {'error': str(exc)}, {}, time.monotonic() - started
        elapsed = time.monotonic() - started
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {'raw': raw[:200].decode(errors='replace')}
        return status, payload, response_headers, elapsed

    def check(self, name: str, ok: bool, detail: str = '') -> None:
        self.steps += 1
        self.passed += ok
        print(f'{"PASS" if ok else "FAIL"}  {name}  {detail}')
        if not ok:
            raise StepFailedError(name)


if __name__ == '__main__':
    sys.exit(main())
