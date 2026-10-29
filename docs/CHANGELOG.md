# Changelog

All notable changes to TicketRush are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Add the logical architecture and the infrastructure and deployment diagrams as draw.io sources with exported SVGs.
- Add the system design document with the purchase flow, tech stack, design goals, and roadmap.
- Add the project README, contributor and agent guidelines in `AGENTS.md`, and the repository `.gitignore`.
- Add the purchase-flow sequence diagram and the PostgreSQL data model diagram.
- Add the failure-handling table covering every component, its detection signal, automatic response, and recovery.
- Add `CLAUDE.md` so Claude Code sessions load the agent guidelines.
- Add the backend skeleton:
  - Django 5.2, DRF, and Celery on PostgreSQL and Redis, laid out to the team's Django house standard.
  - Prefixed environment configuration, with a boot guard for required production values.
  - A one-image Dockerfile for web, workers, and beat.
  - `compose.yaml` for local PostgreSQL and Redis.
- Add the response envelope, the exception handler, and the base API views.
- Add probes:
  - `/system/healthcheck/` (liveness).
  - `/system/readiness/` (PostgreSQL only; the deploy gate).
  - `/system/dependencies/` (PostgreSQL and Redis; token-gated).
- Add OpenAPI docs at `/system/docs/`.
- Add structured JSON logging with a correlation ID on every line. The ID is returned in the `Correlation-ID` header and carried into Celery tasks.
- Add the ActivityLog audit trail.
- Add API request tracking, which stores every write, every error, and every slow request, with secrets redacted.
- Add the CI workflow: ruff, a missing-migration check, and pytest on PostgreSQL and Redis, plus a Docker image build, for every pull request and push to `main` that touches the backend.
- Add events and ticket holds:
  - `GET /api/events/` and `GET /api/events/<uuid>/`, public.
  - `POST /api/events/<uuid>/holds/` reserves stock with one conditional update for 5 minutes, enforces the sale window and the per-user limit, and returns `409` with `SOLD_OUT`, `SALE_NOT_OPEN`, or `PER_USER_LIMIT`.
  - `DELETE /api/holds/<uuid>/` releases a hold early and returns its stock, unless the hold already has an order.
  - The `holds.expire_sweeper` beat task runs every 30 seconds. It expires overdue holds in batches of 500, returns their stock, and expires their pending orders.
- Add idempotency keys for mutating endpoints. The `Idempotency-Key` header is required, and a repeat replays the first response with `Idempotent-Replayed: true`. The same key with a different body returns `422`.
- Add per-user and per-IP hold throttling (`DJANGO_HOLD_THROTTLE_USER_RATE`, `DJANGO_HOLD_THROTTLE_IP_RATE`). New holds are refused with `503 SALES_PAUSED` when Redis is unavailable.
- Add concurrency tests on real PostgreSQL connections: 40 buyers racing for 10 seats, one buyer racing against their own per-user limit, duplicate idempotency keys, and a release racing the sweeper.
- Add Django admin pages for events, holds, orders, and idempotency records. Events get their stock from capacity at creation, and the stock cannot be edited afterward.
- Add checkout and payments:
  - `POST /api/holds/<uuid>/checkout/` commits the order and payment first, then creates the gateway charge with the payment UUID as the gateway idempotency key and the hold expiry as the charge expiry. It needs at least 60 seconds left on the hold and returns `409 HOLD_EXPIRING` otherwise. A retry for the same hold resumes the same order and charge.
  - Gateway calls have a 5-second timeout, two attempts, and a per-process circuit breaker. Failures return `503 PAYMENTS_UNAVAILABLE` and keep the hold.
  - `GET /api/orders/<uuid>/` and `GET /api/me/tickets/` return only the caller's own orders and tickets.
  - `POST /api/webhooks/<provider>/` verifies an HMAC signature with a 5-minute timestamp tolerance before storing anything, stores each provider event once, and returns `200` for duplicates.
  - Paid orders convert their hold and get one HMAC-signed ticket code per seat. A payment that lands after its hold expired takes the stock again if any is left, and otherwise marks the order `paid_unfulfilled`. A failed charge fails the order and keeps the hold, so the buyer can check out again.
- Add a two-phase idempotency variant for actions that call an external service. A pending record older than 30 seconds can be taken over by a retry with the same key and body.
- Add the transactional outbox, relayed by the `outbox.relay` beat task every 2 seconds and published on commit. A message that fails to publish 10 times becomes a dead letter.
- Add dead letters for tasks that exhaust their retries (5 retries with exponential backoff and jitter, capped at 240 seconds), with a replay action in the admin.
- Add the mock payment gateway (`DJANGO_PAYMENT_GATEWAY=mock`): a charge page at `/mock-gateway/charges/<id>/`, a pay endpoint, signed webhooks delivered from the `bulk` queue, and fault injection for latency, errors, duplicate webhooks, and dropped webhooks, edited in the admin.
- Add `DJANGO_PUBLIC_API_URL`, `DJANGO_PAYMENT_GATEWAY`, `DJANGO_MOCK_GATEWAY_WEBHOOK_SECRET`, and `DJANGO_TICKET_SIGNING_KEY`. All but the gateway name are required in production.
- Add a payment gateway registry: an adapter class registers itself with `@register_gateway('<provider>')`, and an unregistered `DJANGO_PAYMENT_GATEWAY` stops the process at boot.
- Add `DJANGO_PAYMENT_WEBHOOK_PROVIDERS`, which lists the providers whose webhooks are accepted. Empty accepts the active gateway only; list both providers while switching so payments started on the old one still complete.

### Changed
- Rename the health endpoints to `/system/healthcheck/`, `/system/readiness/`, and `/system/dependencies/` in the design documents and diagrams.
