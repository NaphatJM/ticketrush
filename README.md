# TicketRush

A flash-sale ticketing system for events with limited seats. Buyers race for a small number of tickets when a sale opens; organizers create events and watch sales live. Every purchase is protected against overselling, and paid orders receive a QR ticket by email.

**1,000 buyers. 100 seats. The same second.** On production, 100 seats sold out in 3.6 s to 1,000 concurrent buyers with 0 errors and 0 oversold, verified in the database after every run.

| | |
| --- | --- |
| Live app | <https://ticketrush.naphat.online> |
| API | <https://api.ticketrush.naphat.online> |
| API docs | <https://api.ticketrush.naphat.online/system/docs/> |

<p align="center"><img src="docs/screenshots/home.webp" alt="TicketRush home page with event search and filters" width="820"></p>

The system design is in [docs/README.md](./docs/README.md), the failure table in [docs/fail-safe.md](./docs/fail-safe.md), and changes in [docs/CHANGELOG.md](./docs/CHANGELOG.md).

```text
backend/    Django API, Celery tasks, and tests
frontend/   Next.js app
loadtest/   Locust scenarios and recorded results
scripts/    Production smoke test
docs/       System design and diagrams
```

## Features

**Buyers**
- Browse events and search by title or venue, filtered by sale status and category.
- Hold seats for 5 minutes with a live countdown; stock returns automatically if the hold expires.
- Pay through a mock payment gateway that can inject faults on demand.
- Receive a QR ticket on the site and by email.

**Organizers**
- Create events with a fixed capacity and a sale window in the Django admin.

**Under the hood**
- Atomic stock reservation, compare-and-set state transitions, and idempotency keys on every mutating endpoint.
- Transactional outbox, separate Celery queues, signed and deduplicated webhooks, payment reconcile, and a circuit breaker on the gateway.
- One correlation ID per request across JSON logs, traces, and metrics in Grafana Cloud.
- Every merge to `main` deploys itself and ends with a smoke test that buys a real ticket.

| Event page | Mobile | API docs |
| --- | --- | --- |
| ![Event page](docs/screenshots/event.webp) | <img src="docs/screenshots/event-mobile.webp" alt="Event page on a phone" width="220"> | ![OpenAPI documentation](docs/screenshots/api-docs.webp) |

## How it works

![Purchase flow: hold, checkout, pay, webhook, ticket](docs/slides/04-purchase-flow.webp)

### Architecture

![Logical architecture: Next.js BFF, Django API, Celery workers, PostgreSQL, Redis, and Grafana Cloud](docs/screenshots/architecture.webp)

### Infrastructure and deployment

![Infrastructure: Vercel, Railway services, private data network, Grafana Cloud, and the GitHub Actions pipeline](docs/screenshots/infrastructure.webp)

The draw.io sources, the [purchase sequence](docs/diagrams/purchase-sequence.drawio.svg), and the [data model](docs/diagrams/data-model.drawio.svg) are in `docs/diagrams/`.

## Design goals

### Never oversell

![Atomic reservation, expiry checks, compare-and-set transitions, and idempotency keys](docs/slides/07-never-oversell.webp)

### Failures are handled, not hoped away

![Transactional outbox, separate queues, late acks, retries, signed webhooks, and reconcile](docs/slides/08-failure-handling.webp)

### Every request can be followed

![OpenTelemetry to Grafana Cloud with one correlation ID per request](docs/slides/09-observability.webp)

### Every merge to main deploys itself

![CI, then web, workers, verify, and annotate](docs/slides/10-ci-cd.webp)

## Load test results

Every run targets production and ends with `loadtest_verify`, which runs up to 13 checks on stock, holds, orders, payments, tickets, outbox, and dead letters straight from PostgreSQL. Scenarios and how to run them are in [loadtest/README.md](./loadtest/README.md).

![Runs: P1 flash sale, journey, and R1 to R6 with their pass conditions](docs/slides/11-load-test-setup.webp)

### P1 flash sale: 100 seats, 1,000 buyers

100 won a seat, 900 were told sold out, 0 errors, 0 oversold, across 90,420 requests.

![P1 flash sale results with p50, p95, and p99 per request](docs/slides/12-flash-sale-result.webp)

### Journey: from pay to ticket in 4.3 s

200 users bought, declined, released, and abandoned for 6 minutes at 175 req/s: 4,816 orders paid and ticketed, 0 failed of 62,964 requests.

![Journey results with p50, p95, and p99 per endpoint](docs/slides/13-journey-result.webp)

### Find the bottleneck, fix it, run it again

Moving webhooks off the email queue, polling orders with backoff, and recycling Gunicorn workers cut time to ticket from 29 s to 4.3 s at p50 and from 62 s to 9.7 s at p99.

![Journey time to ticket before and after the fixes](docs/slides/14-optimization.webp)

### Faults injected, invariants held

![R1 to R6: duplicate webhooks, replayed keys, gateway errors and timeouts, dropped webhooks, and a worker restart](docs/slides/15-fault-injection.webp)

### What the load test found

![The scheduler was down, and the outbox hid it](docs/slides/16-scheduler-lesson.webp)

## Stack

Frontend: Next.js on Vercel. Backend: Django + Django REST Framework · Celery + Redis · PostgreSQL on Railway. Payments: mock gateway with fault injection. Email: Resend. Observability: OpenTelemetry · Grafana Cloud. Load testing: Locust. CI/CD: GitHub Actions.

## Local development

Requirements: Python 3.13 with [uv](https://docs.astral.sh/uv/), and Docker.

```bash
docker compose up -d --wait          # PostgreSQL and Redis
cd backend
cp .env.example .env
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

| Command (in `backend/`) | Purpose |
| --- | --- |
| `uv run pytest` | Run the test suite against the local PostgreSQL and Redis |
| `uv run ruff check . && uv run ruff format --check .` | Lint and format check |
| `uv run celery -A ticketrush worker -Q critical,gateway,bulk -l info` | Run a Celery worker (add `--pool=solo` on Windows) |
| `uv run celery -A ticketrush beat -l info` | Run the scheduler for the outbox relay, hold sweeper, payment reconcile, and token cleanup |
| `uv run python manage.py seed_mockdata [--buyers N]` | Create the demo catalog (14 small and medium events in every sale status) and optional load-test buyers `mock-buyer-00001`...; safe to rerun |
| `uv run python manage.py purge_mockdata [--dry-run]` | Delete the demo catalog with everything bought on it and the mock users, for a clean load-test run |

Environment variables are listed in [backend/.env.example](./backend/.env.example). Django reads only `DJANGO_`-prefixed variables.

| Endpoint | Purpose |
| --- | --- |
| `/system/healthcheck/` | Liveness; touches no dependency |
| `/system/readiness/` | Deploy gate; checks PostgreSQL |
| `/system/dependencies/` | PostgreSQL and Redis status; needs `X-Readiness-Token` or a staff session |
| `/system/docs/` | OpenAPI documentation |
| `/api/` | Auth, events, holds, checkout, orders, tickets, and payment webhooks; see `/system/docs/` |
| `/admin/` | Django admin for organizers |

### Frontend

Requirements: Node.js 24 and pnpm 10. The Next.js app talks to the API only from the server: route code and server actions hold the JWTs in an encrypted, httpOnly session cookie, so the browser never sees a token.

```bash
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev                             # http://localhost:3000
```

| Command (in `frontend/`) | Purpose |
| --- | --- |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | Generate route types and run the TypeScript check |
| `pnpm build` | Production build |

Environment variables are listed in [frontend/.env.example](./frontend/.env.example). `BFF_SHARED_SECRET` must match `DJANGO_BFF_SHARED_SECRET` on the API, or every buyer is throttled under the frontend server's IP.

### Smoke test

```bash
python scripts/smoke_test.py [--api URL] [--event UUID]
```

Buys one ticket end to end against a live API (production by default): register, hold with a key replay, checkout, mock payment, and the ticket. It needs only the Python standard library and exits 1 on the first failed step. Each run leaves a user and a paid one-ticket order, so pass `--event` with a mock event to keep real events' stock.

### Deploy

Pushes to `main` deploy through `.github/workflows/deploy.yml` once CI passes: `web` first (its pre-deploy command runs the migrations), then `worker-critical`, `worker-bulk`, and `beat`, each waited on until Railway reports it live, then a readiness wait and the smoke test. Railway autodeploy stays disabled on every service so a push deploys once.

| GitHub setting | Purpose |
| --- | --- |
| `RAILWAY_TOKEN` (secret) | Railway project token for the production environment |
| `GRAFANA_ANNOTATION_TOKEN` (secret, optional) | Grafana service account token; without it the annotation step is skipped |
| `GRAFANA_URL` (variable, optional) | Grafana stack URL, such as `https://<stack>.grafana.net` |
| `SMOKE_EVENT_UUID` (variable, optional) | Event the post-deploy smoke test buys from; point it at a mock event to keep real events' stock |

Roll back by redeploying the previous deployment in Railway.
