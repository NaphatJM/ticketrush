# Failure handling

How TicketRush behaves when each part of the system fails. Every row is an expected failure with a defined response; none of them may end in oversold stock, a lost paid order, a double charge, or a silent success.

## Principles

- **PostgreSQL is the source of truth.** Every state change, and every job it triggers, commits in one transaction through the outbox. Anything else can be lost and rebuilt from the database.
- **Every transition is a compare-and-set.** Holds and orders change state only with `WHERE status = <expected>`, and stock moves only when that update changed a row. Two actors racing on the same hold cannot both win.
- **Every retry is safe.** API mutations take an idempotency key created per click, the gateway receives `payment.id` as its idempotency key, webhooks are deduplicated by provider event ID, and Celery tasks tolerate duplicate delivery.
- **Every external call is bounded.** Each has a timeout, a retry budget with exponential backoff and jitter, and a final destination: success, an explicit error to the caller, or a dead letter that raises an alert.
- **Time-based rules are checked on use.** A hold past `expires_at` is rejected even if the sweeper has not run.
- **Every failure is visible.** Each row below names the signal that detects it.

## Health endpoints

- `/system/healthcheck/` touches no dependency; it only shows that the process answers.
- `/system/readiness/` checks PostgreSQL only. Railway uses it to decide whether a new deployment may receive traffic, so a Redis outage cannot block a deploy or a rollback.
- `/system/dependencies/` checks PostgreSQL, Redis, and the outbox lag. It requires the readiness token because it reveals the topology; alerts and the synthetic check send that token.

## Failure table

| Component | Failure | Detection | Automatic response | What the buyer sees | Recovery |
| --- | --- | --- | --- | --- | --- |
| Next.js BFF (Vercel) | Function error or API unreachable | Vercel logs, synthetic check | API calls use a timeout; the BFF returns a typed error page | "Something went wrong, try again" with the `cid` | Retry is safe because the BFF reuses the same idempotency key |
| Django API | Process crash or out of memory | 5xx rate alert, `/system/dependencies/` | Railway's restart policy restarts the service; a request either committed or did not | Retry returns the original result for the same key | Automatic |
| Django API | Overload during a sale | p95 latency alert, throttle counter | Per-user and per-IP throttling on holds returns `429` with `Retry-After` | "Too many requests, retrying in N seconds" | Scale web replicas |
| Django API | Same idempotency key, different body | `422` counter | `422 idempotency_key_reused`; a concurrent duplicate gets `409 in_progress` | Client error, nothing charged twice | Client bug; fix the caller |
| Django API | Process dies between committing a checkout and saving its charge | Pending idempotency record older than 30 s | The order and payment are already committed; a retry with the same key takes over the stale record and resumes them, and the gateway returns the same charge for the same `payment.id` | "Something went wrong, try again"; the retry continues the same order | Automatic on retry |
| PostgreSQL | Unavailable | 5xx rate alert, `/system/dependencies/` | API returns `503`; no partial writes because each step is one transaction | "Service unavailable, try again" | Railway restores the service; no data repair needed |
| PostgreSQL | Connections exhausted | Connection error logs, pool metrics | Connection count is budgeted: gunicorn workers x web replicas + Celery concurrency + beat stays below the server limit | Slow or `503` responses | Lower worker counts or add a pooler |
| PostgreSQL | Contention on one event row | Hold latency on the dashboard | The conditional `UPDATE ... WHERE available >= q` serializes safely and never oversells | Slower response, never a wrong one | Optimize only after a measured baseline |
| Redis | Unavailable | `/system/dependencies/`, outbox lag alert | New holds, logins, and registrations are rejected with `503` because their throttles fail closed; token refresh, checkout of existing holds, and webhooks still commit, and their jobs wait in the outbox | "Ticket sales are paused, try again shortly"; signed-in buyers who already hold a ticket can still pay | Relay drains the outbox when Redis returns |
| Celery beat | Stopped | No beat heartbeat for 2 min, outbox lag alert | The on-commit publish still enqueues new jobs; expired holds are rejected on use but their stock is not returned until the sweeper runs, so the event may show sold out too early | Possible early "sold out" (under-selling, never overselling) | Restart beat (exactly one replica) |
| Outbox relay | Same row published twice | Duplicate deliveries are counted by the tasks | Tasks are idempotent: the order update matches only `pending_payment`, and tickets are unique on `(order_id, seq)` | Nothing | Automatic |
| Outbox relay | Row keeps failing to publish | `attempts` reaches 10, dead letter alert | The row moves to dead letters instead of blocking newer rows | Order shows "processing" | Operator fixes the cause and replays the dead letter |
| worker-critical | Child process dies during a task | Task redelivered, retry counter | `acks_late` with `task_reject_on_worker_lost` requeues the task at once; the task is idempotent | Ticket appears a few seconds later | Automatic |
| worker-critical | Whole container dies (restart or out of memory) | Task redelivered after the visibility timeout | Redis redelivers unacknowledged tasks after `visibility_timeout`, set to 5 minutes, just above the longest task time limit | Ticket appears up to about 5 minutes later | Automatic |
| worker-critical | Task keeps failing | Dead letter alert | 5 retries with backoff, then a dead letter | Order shows "processing" | Operator fixes the cause and replays the dead letter |
| worker-bulk | Backlog | Queue depth alert | Separate queue, so ticket issuing is not delayed | Ticket is in "My tickets"; email is late | Scale bulk workers |
| Payment gateway | Slow or erroring | Gateway latency and error metrics, circuit breaker state | Timeout and retries with `payment.id` as the gateway idempotency key, so a retry never creates a second charge; each API process opens its circuit after 5 failed checkouts and returns `503 payments_unavailable` for 30 s before one trial call | "Payments are temporarily unavailable"; the hold is kept until it expires | Circuit half-opens and closes when calls succeed |
| Payment gateway | Webhook never arrives | Payments pending longer than 5 min | Reconcile job asks the gateway for the real status and emits the same outbox event a webhook would | Order completes a few minutes late | Automatic |
| Payment gateway | Charge fails or expires | `charge.failed` webhook or reconcile result | Order becomes `failed`; the hold stays active until it expires, so the buyer can retry checkout | "Payment failed, try again" | Automatic |
| Webhook | Delivered twice | Unique `(provider, provider_event_id)` | `INSERT ... ON CONFLICT DO NOTHING`; the outbox row is written only when the insert happened; the response is `200` | Nothing | Automatic |
| Webhook | Bad signature or timestamp outside tolerance | Rejected-webhook counter | `401` before any processing, which also blocks replayed requests | Nothing | Investigate the source if the counter rises |
| Webhook | Arrives after the hold expired | The hold update to `converted` matches no row | Re-take stock with `available >= q` and no sale-window check; if none is left, mark the order `paid_unfulfilled` and alert | "We are confirming your ticket" | Operator handles it (refunds are out of scope) |
| Hold sweeper | Buyer abandons the purchase | Expired holds counter | Each hold is expired only if still `active`, its stock is returned in the same transaction, and its pending order becomes `expired` | The hold countdown ends | Automatic |
| Resend | Unavailable | Retry counter, dead letter alert | Up to 8 retries with backoff capped below the visibility timeout, then a dead letter; the outbox ID is sent as the idempotency key | Ticket is valid and visible in "My tickets" | Replay the dead letter |
| Grafana Cloud | Unavailable or quota reached | Missing data on dashboards | Telemetry export is asynchronous with bounded buffers; the app keeps serving and drops telemetry instead of blocking | Nothing | Data resumes when export recovers |
| Deploy | Broken release | Railway health check on `/system/readiness/`, then the pipeline smoke test | A release that fails the health check never receives traffic; a smoke-test failure stops the pipeline and alerts | Previous version, or errors until rollback if only the smoke test caught it | Redeploy the previous Railway deployment |
