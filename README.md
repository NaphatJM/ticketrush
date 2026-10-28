# TicketRush

A flash-sale ticketing system for events with limited seats. Buyers race for a small number of tickets when a sale opens; organizers create events and watch sales live. Every purchase is protected against overselling, and paid orders receive a QR ticket by email.

The system design, architecture diagrams, and design goals are in [docs/README.md](./docs/README.md). Changes are recorded in [docs/CHANGELOG.md](./docs/CHANGELOG.md).

The applications live in separate workspace packages:

```text
backend/    Django API, Celery tasks, and tests
frontend/   Next.js app
loadtest/   Locust scenarios and recorded results
docs/       System design and diagrams
```

| | |
| --- | --- |
| Live app | _not deployed yet_ |
| API docs | _not deployed yet_ |

## Stack

Frontend: Next.js on Vercel. Backend: Django + Django REST Framework · Celery + Redis · PostgreSQL on Railway. Payments: mock gateway with fault injection. Observability: OpenTelemetry · Grafana Cloud. Load testing: Locust. CI/CD: GitHub Actions.
