# TicketRush

A flash-sale ticketing system for events with limited seats. Buyers race for a small number of tickets when a sale opens; organizers create events and watch sales live. Every purchase is protected against overselling, and paid orders receive a QR ticket by email.

The system design, architecture diagrams, and design goals are in [docs/README.md](./docs/README.md). Changes are recorded in [docs/CHANGELOG.md](./docs/CHANGELOG.md).

The repository is organized into these packages (built as the project progresses):

```text
backend/    Django API, Celery tasks, and tests
frontend/   Next.js app
loadtest/   Locust scenarios and recorded results
docs/       System design and diagrams
```

| | |
| --- | --- |
| Live app | <https://ticketrush.naphat.online> |
| API | <https://api.ticketrush.naphat.online> |
| API docs | <https://api.ticketrush.naphat.online/system/docs/> |

## Stack

Frontend: Next.js on Vercel. Backend: Django + Django REST Framework · Celery + Redis · PostgreSQL on Railway. Payments: mock gateway with fault injection. Observability: OpenTelemetry · Grafana Cloud. Load testing: Locust. CI/CD: GitHub Actions.

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
| `uv run celery -A ticketrush worker -Q critical,bulk -l info` | Run a Celery worker (add `--pool=solo` on Windows) |
| `uv run celery -A ticketrush beat -l info` | Run the scheduler for the outbox relay, hold sweeper, and token cleanup |
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
