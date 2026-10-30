# Load tests

Locust scenarios that measure three things against the live API:

- **Performance:** how much load the backend takes and where it saturates.
- **User journey:** whether real buying paths succeed, and how long a buyer waits for a ticket.
- **Reliability:** whether the invariants hold while the payment gateway misbehaves.

Every run ends with `loadtest_verify`, which checks the stock and ticket invariants in the database.

## Setup

```bash
cd loadtest
uv venv && uv pip install -r requirements.txt
```

Buyers are the `mock-buyer-*` accounts from `seed_mockdata`. They have no email, so a run sends nothing to Resend. Load test events belong to the mock organizer, and `purge_mockdata` removes them with every hold, order, and ticket bought on them.

On the API host (for Railway: `railway ssh` into `web`, then use `/opt/venv/bin/python`):

```bash
python manage.py seed_mockdata --buyers 1000
python manage.py seed_loadtest --scenario flash --opens-in 420   # prints LOADTEST_EVENT=<uuid>
```

| Variable | Value |
|---|---|
| `LOADTEST_EVENT` | UUID printed by `seed_loadtest` |
| `LOADTEST_BFF_SECRET` | Same value as the API's `DJANGO_BFF_SHARED_SECRET` |
| `LOADTEST_BUYER_PASSWORD` | Password given to `seed_mockdata` |
| `LOADTEST_FIRST_BUYER` | First buyer number; default `1` |
| `LOADTEST_SUMMARY` | Optional path for the flash sale summary JSON |
| `LOADTEST_CLICK_SPREAD_SECONDS` | Flash sale: spread of the clicks after opening; default `1.0` |
| `LOADTEST_REPLAY_RATE` | Journey: share of holds and checkouts sent twice with one Idempotency-Key; default `0` |
| `LOADTEST_PAY_TIMEOUT_SECONDS` | Journey: how long to wait for an order to turn paid; default `60` |

Locust sends `BFF-Secret` and a distinct `BFF-Client-IP` per buyer, as the Vercel BFF does, so the per-IP throttles see 1,000 clients instead of one machine. If the secret is wrong the API ignores the client IP: sign-in hits the 30/min per-IP limit, and the flash sale summary shows far fewer `buyers_finished` than buyers.

## Run everything

`run_all.sh` runs P1, the journey, and R1 to R6 in sequence from Git Bash or any POSIX shell, in about 80 minutes. It reads `.env.loadtest`, reaches production through `railway ssh` (link the project with `railway link` first), seeds an event per run, sets and resets the gateway faults, samples saturation on `worker-bulk`, and runs `loadtest_verify` after each run. Remote commands are retried 5 times over about 5 minutes, a run stops when it cannot seed or set faults, and faults are reset on exit, even after Ctrl+C. While R3 to R6 run, real buyers on production see the same faults.

```bash
bash run_all.sh check              # read-only: Locust, SSH to web and worker-bulk, current faults
bash run_all.sh                    # every run; results in results/<date>_<time>/
bash run_all.sh r5 r6              # only the named runs: p1 journey r1 r2 r3 r4 r5 r6
bash run_all.sh --cleanup [runs]   # the same, then purge_mockdata and seed_mockdata
bash run_all.sh reset              # set every fault back to 0
```

`summary.txt` lists each run's Locust and verify exit codes. Locust exits 1 on any failed request, so R3 to R5 exit 1 by design; judge them by the table below and the verify JSON.

## Runs

Keep each run under 10 minutes; Railway bills CPU time. Write results to `results/<date>/`, which git ignores.

### P1 Flash sale (performance)

1,000 buyers sign in while the sale is upcoming, refresh the event page every 2 to 5 seconds, and each tries to hold one ticket within a second of the opening. Capacity is 100.

```bash
# --opens-in 420 leaves time for sign-in: 5 users/s takes about 200 s, and PBKDF2 makes each sign-in slow under load.
locust -f flash_sale.py --headless -u 1000 -r 5 -t 9m --host https://api.ticketrush.naphat.online \
  --csv results/2026-10-30/p1 --csv-full-history --html results/2026-10-30/p1.html
```

Pass: `buyers_started` = `buyers_finished` = 1,000, `won` = 100 exactly, `error` = 0, no 5xx, and `loadtest_verify` passes.

### Journey (user journey)

Seed with `--scenario journey` (capacity 20,000, open now; 200 users buy about 5,000 tickets in 6 minutes). Each buyer repeats journeys with 1 to 5 s between them:

| Weight | Journey |
|---|---|
| 60 | list, event, hold 1 or 2, checkout, gateway page, pay, poll the order until paid, my tickets |
| 15 | the same, but the first payment is declined; check out again and pay |
| 10 | hold, then release |
| 10 | hold, sometimes check out, then leave; the sweeper returns the stock after 5 minutes |
| 5 | browse only |

```bash
locust -f journey.py --headless -u 200 -r 10 -t 6m --host https://api.ticketrush.naphat.online \
  --csv results/2026-10-30/journey --csv-full-history --html results/2026-10-30/journey.html
```

`loadtest_verify` reads one snapshot, so it can run at any time; wait until `overdue_active_holds` is 0 if the report should show swept holds as expired.

### Reliability (R1 to R6)

Run the journey with 100 users, one fault at a time. Set faults in the admin under *Fault config*, and reset them after each run.

| Run | Fault | Expect |
|---|---|---|
| R1 | Duplicate webhook rate 0.5 | No extra tickets; `loadtest_verify` passes |
| R2 | `LOADTEST_REPLAY_RATE=0.3` | Every `REPLAY` entry succeeds; stock is taken once per hold |
| R3 | Charge error rate 1.0 with charge latency 2,000 ms | Checkout fails with `503 PAYMENTS_UNAVAILABLE`. Each failed checkout makes 2 gateway calls; after 5 failed checkouts in one gunicorn worker its breaker opens and checkout fails without waiting for the gateway. 30 s after the last failure one trial call goes through, and the breaker closes when a trial succeeds |
| R4 | Charge latency above the 5 s gateway timeout | A checkout fails after 2 attempts of 5 s each and holds one of the 8 gunicorn threads meanwhile, so latency rises across the API until the breaker opens. No payment has two successful charges |
| R5 | Dropped webhook rate 0.2 | Those orders expire with their holds and the stock returns; `charges_succeeded_unrecorded` counts them. Known gap: there is no reconcile job, so a payment whose webhook is lost is not recovered |
| R6 | Restart `worker-critical` during R1 | Late-acked tasks are redelivered; every paid order still gets its tickets |

## Verify and sample

```bash
python manage.py loadtest_verify --event <uuid> --since 2026-10-30T14:00:00+00:00   # run start with offset; exits 1 on a failed check
python manage.py loadtest_sample --interval 5 --count 120 > saturation.csv       # run during the test
```

Run the sampler on a worker service rather than `web`, so it does not compete with the API for CPU.

## Metrics

| Metric | Source |
|---|---|
| Response time, average, P50/P90/P95/P99 | Locust `*_stats.csv` and the HTML report, per request name |
| Requests per second, error rate | Locust stats; `*_stats_history.csv` over time |
| Concurrent users | `User Count` in `*_stats_history.csv` |
| Throughput (successful work per second) | `OUTCOME hold won` in P1, `JOURNEY buy` in the journey: their RPS, excluding failures |
| Journey success rate and time to ticket | `JOURNEY` rows: failures over requests, and the `time to ticket` percentiles |
| Correctness | `loadtest_verify` JSON |
| Saturation: database connections, queue backlog, outbox, unprocessed webhooks | `loadtest_sample` CSV |
| CPU, memory, network per service | Railway metrics for `web`, `worker-critical`, `worker-bulk`, Postgres, Redis; screenshot the run window |

The API has 2 gunicorn workers with 4 threads each, so 8 requests run at once; queueing beyond that shows as latency, not as a separate metric. Latency includes the round trip from the Locust machine to Railway; record where Locust ran.

## Clean up

After the workers drain:

```bash
python manage.py purge_mockdata --yes
python manage.py seed_mockdata
```
