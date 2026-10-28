# AGENTS.md

Instructions for coding agents working in this repository.

## Project

TicketRush is a flash-sale ticketing system. The domain is small on purpose; the work is in the backend: concurrency control, background jobs, failure handling, observability, and CI/CD. Read [docs/README.md](docs/README.md) before changing behavior.

```text
backend/    Django + DRF API, Celery tasks, tests
frontend/   Next.js app (BFF route handlers call the API)
loadtest/   Locust scenarios and recorded results
docs/       System design, diagrams, changelog
```

## Invariants

Code must keep these true. A change that weakens one needs a design discussion first, not a quiet workaround.

- Tickets are never oversold. Reserve stock with an atomic conditional update in PostgreSQL, never with a read-then-write.
- A hold is valid only until its `expires_at`. Check expiry wherever a hold is used; do not rely on the sweeper having run.
- Hold and order transitions are compare-and-set: `UPDATE ... WHERE status = <expected>`. Move stock or write outbox rows only when that update changed a row.
- Mutating endpoints accept an idempotency key, and a repeated key returns the original result.
- Jobs triggered by a domain change are written to the outbox in the same transaction as that change.
- Celery tasks tolerate duplicate delivery and run with `acks_late`. Ticket issuing and email use separate queues. Keep every retry countdown below the Redis `visibility_timeout`, or the broker redelivers the task while it waits.
- Calls to the payment gateway send `payment.id` as the gateway idempotency key.
- Webhooks are verified by signature before any processing and deduplicated by provider event ID.
- Every external call has a timeout. Never widen a failure into a silent success.
- Every log line carries the request `cid`. Logs are structured JSON.
- Initialize OpenTelemetry after fork (gunicorn `post_fork`, Celery `worker_process_init`); exporters started before fork lose their spans.
- Metric labels use route templates and bounded values, never raw paths, user IDs, or other unbounded input. The Grafana Cloud free tier allows 10k active series.
- Secrets come from environment variables only. Never commit `.env` files, keys, or tokens.

## Documentation

- Write repository content in English.
- `README.md` at the root is the product page: what the app does, features, screenshots, setup, environment variables, and scripts. Add a section only when the thing it describes exists.
- `docs/README.md` holds the system design. Update it when the architecture or a design goal changes, and tick the roadmap as items land.
- Record every user-visible or operational change in [docs/CHANGELOG.md](docs/CHANGELOG.md) under `[Unreleased]`, in the same change as the code.

## Diagrams

- Diagrams live in `docs/diagrams/` as `.drawio` sources with exported `.drawio.svg` files. Commit both, and re-export the SVG whenever the source changes.
- No grid background: set `grid="0"` on `mxGraphModel`.
- Put connectors on a `Connections` layer below a `Components` layer. Lines and labels must never cover text.
- Render and look at the result before committing:

  ```bash
  docker run --rm --shm-size=2g -v "$PWD/docs/diagrams:/data" rlespinasse/drawio-desktop-headless \
    -x -f svg -e -b 10 -o /data/<name>.drawio.svg /data/<name>.drawio
  ```

  The renderer crashes without `--shm-size`.

## Git

- `main` is production. Work on a short-lived branch and merge through a pull request.
- Commit messages follow Conventional Commits, for example `feat(holds): release expired holds in a beat task`.
- Do not commit or push without explicit approval from the repository owner.
