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
- Add the CI workflow: ruff, a missing-migration check, and pytest on PostgreSQL and Redis, plus a Docker image build, for every pull request and every push to `main` or `develop` that touches the backend.
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
- Add JWT authentication:
  - `POST /api/auth/register/` creates a buyer account and returns the user with a token pair. A taken username returns `409 USERNAME_TAKEN`, and weak passwords are refused by Django's password validators.
  - `POST /api/auth/login/` returns an access token (15 minutes) and a refresh token (7 days). Every failure returns the same `401 NOT_AUTHENTICATED`.
  - `POST /api/auth/refresh/` rotates the refresh token and blacklists the old one, so a reused refresh token is refused.
  - Tokens identify the user by UUID. API calls accept `Authorization: Bearer <access>`.
- Add login throttling per username (`DJANGO_LOGIN_THROTTLE_USERNAME_RATE`) and per IP for login and register together (`DJANGO_AUTH_THROTTLE_IP_RATE`). Both refuse with `503 SIGN_IN_PAUSED` when Redis is unavailable; refresh is not throttled. The username limit counts a name the way login reads it, so padding or a numeric JSON value does not open a new bucket.
- Add the `accounts.flush_expired_tokens` beat task, which deletes expired refresh-token records once a day on the `bulk` queue. The admin lists issued refresh tokens without showing the tokens themselves.
- Production refuses to boot when `DJANGO_SECRET_KEY` is shorter than 32 bytes, because it signs JWTs.
- Add the ticket email: paying an order queues `notify.send_ticket_email` on the `bulk` queue through the outbox. It sends one inline QR code per ticket through Resend with an idempotency key per order, so a duplicate delivery sends one email. Sends are capped at 5 per second per worker. Transient failures retry 8 times and then become a dead letter; a message Resend rejects, or a used-up quota, becomes a dead letter at once.
- Add `DJANGO_RESEND_API_KEY` (required in production; empty disables ticket emails elsewhere) and `DJANGO_EMAIL_FROM`. The default sender, `onboarding@resend.dev`, delivers only to the Resend account's own address; other recipients need a verified domain.
- A task whose retry cannot be published because the broker is unavailable now becomes a dead letter instead of being dropped.
- Add event details for the storefront: summary, description, important info, category, presenter, banner URL, venue name, address, and map URL, and an end time. Banner and map links must be HTTPS. The admin groups the fields and previews the banner.
- Add `is_published`. New events start as drafts, which the API hides and which cannot be held; events that existed before stay published.
- Add `sale_status` (`upcoming`, `on_sale`, `sold_out`, `closed`) to events, and `?status=` and `?category=` filters to `GET /api/events/`. The list omits the long text that `GET /api/events/<uuid>/` returns.
- Add `GET /api/auth/me/` and `GET /api/me/orders/`. Orders include an event summary, the latest payment, and the issued tickets.
- Add the Next.js storefront in `frontend/`:
  - Pages for the event list, event details with holding and a 5-minute countdown, the mock gateway's payment page, an order page that follows the payment until the tickets are issued, my tickets with QR codes, sign in, and sign up.
  - The browser holds only an encrypted httpOnly session cookie. The server keeps the JWTs, refreshes the access token before it expires, and sends `BFF-Secret` and `BFF-Client-IP` with every API call.
  - Holds and checkouts send a new idempotency key per attempt and reuse it when a response is lost.
  - Every API call has a 10-second timeout, and error messages show the API's `Correlation-ID`.
- Add the frontend CI job: lint, typecheck, production build, and a dependency audit.
- Add `DJANGO_BFF_SHARED_SECRET`. A request that carries it in `BFF-Secret` is counted under the IP in `BFF-Client-IP` by the IP throttles and the audit log, so buyers behind the frontend no longer share one bucket. Production refuses a secret shorter than 32 bytes.
- Add the `seed_mockdata` and `purge_mockdata` management commands: an idempotent demo catalog of 8 small and 6 medium events across every sale status plus drafts, optional load-test buyers, and a purge that removes mock events with their purchases and audit-logs both actions.
- Add Locust load tests in `loadtest/`: a 1,000-buyer flash sale, weighted user journeys, and reliability runs under mock gateway faults. Locust sends BFF headers so per-IP throttles see one client per buyer.
- Add the `seed_loadtest`, `loadtest_verify`, and `loadtest_sample` management commands: a purge-able event per run, a read-only stock and ticket invariant check that exits 1 on failure, and CSV readings of database connections and queue backlogs.
- Add OpenTelemetry export over OTLP/HTTP, enabled by `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`:
  - Traces for Django, PostgreSQL, Redis, Celery, and outgoing HTTP. Request spans carry the `cid`, and the context travels into Celery tasks and the mock gateway's webhook.
  - Logs exported over OTLP with the `cid`. JSON log lines gain `trace_id` and `span_id`.
  - Metrics: hold requests by result, gateway charges by outcome with latency, webhooks by result, and task outcomes including dead letters. Beat also reports queue lengths, outbox backlog and age, pending dead letters, unprocessed webhooks, stock per event on sale by event UUID, and seconds since it last sent a task.
  - Each gunicorn worker, Celery pool process, and beat starts its exporters after fork. Health and readiness probes are not traced, and export failures are logged to stdout.

### Changed
- Rename the health endpoints to `/system/healthcheck/`, `/system/readiness/`, and `/system/dependencies/` in the design documents and diagrams.
- Ticket emails are sent from `noreply@mail.naphat.online`, a Resend-verified domain, so any buyer receives them.
- The production API is served at `https://api.ticketrush.naphat.online`.
- The storefront is served at `https://ticketrush.naphat.online` from Vercel.
- Move the Django admin from `/staff-admin/` to `/admin/`.
- Redesign the ticket email: event banner, date and time range, venue with a map link, one ticket card per QR code, an order summary with unit price and payment time, and the event's important info. The plain-text part carries the same details.
- The `event` field of an order is now an event summary object instead of a UUID, and tickets embed the same summary with the banner and venue.
- Correct the data model diagram to the real columns: `bigint` primary and foreign keys, a unique `uuid` per domain row, and `created_on` and `updated_on` timestamps. The sequence diagram uses the real API paths, and the docs name `payment.uuid` as the gateway idempotency key.
- Gunicorn replaces a worker after 20,000 requests instead of 1,000, set by `GUNICORN_MAX_REQUESTS`. At 1,000 the flash sale load test restarted a worker every 5 seconds and stalled the API.
- The OpenAPI docs now describe each endpoint with its own summary, description, and tag, declare the `{status, data}` envelope and the paginated list shape that the API actually returns, and list the error responses and the `Idempotent-Replayed` header.
