#!/usr/bin/env bash
# Runs the load test scenarios against production; see README.md.
# Usage: bash run_all.sh check | reset | [--cleanup] [p1 journey r1 r2 r3 r4 r5 r6]
set -uo pipefail
cd "$(dirname "$0")"

set -a
source .env.loadtest
set +a
: "${LOADTEST_HOST:?Set LOADTEST_HOST in .env.loadtest}"
: "${LOADTEST_BFF_SECRET:?Set LOADTEST_BFF_SECRET in .env.loadtest}"
: "${LOADTEST_BUYER_PASSWORD:?Set LOADTEST_BUYER_PASSWORD in .env.loadtest}"

# Git Bash rewrites /opt/... arguments into Windows paths before railway sees them.
export MSYS_NO_PATHCONV=1

LOCUST=.venv/Scripts/locust
[ -x "$LOCUST" ] || LOCUST=.venv/bin/locust
OUT="results/$(date +%Y-%m-%d_%H%M)"
JOURNEY_TIME=6m
ALL_SCENARIOS=(p1 journey r1 r2 r3 r4 r5 r6)
RESULTS=()

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

stop() {
    log "Stopping: $*"
    exit 1
}

# railway exits 1 on API or DNS errors and ssh exits 255 when it cannot connect, so every failure is retried.
remote() {
    local attempt
    for attempt in 1 2 3 4 5; do
        railway ssh -s "$1" -- "${@:2}" && return 0
        [ "$attempt" -lt 5 ] || break
        log "Command on $1 failed (attempt $attempt of 5); retrying in $((attempt * 30)) s" >&2
        sleep $((attempt * 30))
    done
    return 1
}

manage() { remote web /opt/venv/bin/python manage.py "$@"; }

# Ships Python through base64 so no quoting survives the railway ssh hop.
django_exec() {
    local encoded
    encoded=$(printf '%s\n' "$1" | base64 -w0)
    remote web "echo $encoded | base64 -d | /opt/venv/bin/python manage.py shell"
}

set_faults() {
    log "Faults: latency_ms=$1 error_rate=$2 duplicate_webhook_rate=$3 drop_webhook_rate=$4"
    django_exec "from mockgateway.models import FaultConfig
config = FaultConfig.load()
config.latency_ms, config.error_rate, config.duplicate_webhook_rate, config.drop_webhook_rate = $1, $2, $3, $4
config.save()
print('FAULTS', config.latency_ms, config.error_rate, config.duplicate_webhook_rate, config.drop_webhook_rate)"
}

faults() { set_faults "$@" || stop "could not set faults"; }

no_faults() { faults 0 0.0 0.0 0.0; }

seed() {
    local output
    output=$(manage seed_loadtest "$@" | tr -d '\r') || return 1
    printf '%s\n' "$output" >&2
    grep -o 'LOADTEST_EVENT=[0-9a-f-]*' <<<"$output" | cut -d= -f2
}

utc_now() { date -u +%Y-%m-%dT%H:%M:%S+00:00; }

# run <name> <locustfile> <users> <rate> <time> <event> <since> [VAR=value...]
run() {
    local name=$1 file=$2 users=$3 rate=$4 duration=$5 event=$6 since=$7
    shift 7
    local samples=$((${duration%m} * 12 + 12))
    log "$name: $users users, $duration, event $event"
    # Sampled once without retries, and bounded, so a dropped connection cannot hold up the run.
    timeout $((samples * 5 + 60)) railway ssh -s worker-bulk -- /opt/venv/bin/python manage.py loadtest_sample --interval 5 --count "$samples" \
        >"$OUT/${name}_saturation.csv" 2>/dev/null &
    local sampler=$!
    env LOADTEST_EVENT="$event" "$@" "$LOCUST" -f "$file" --headless -u "$users" -r "$rate" -t "$duration" \
        --host "$LOADTEST_HOST" --csv "$OUT/$name" --csv-full-history --html "$OUT/$name.html" >"$OUT/$name.log" 2>&1
    local locust_exit=$?
    tail -n 30 "$OUT/$name.log"
    wait "$sampler"
    verify "$name" "$event" "$since" "$locust_exit"
}

verify() {
    local name=$1 event=$2 since=$3 locust_exit=$4
    log "$name: waiting 120 s for the workers to drain"
    sleep 120
    manage loadtest_verify --event "$event" --since "$since" | tr -d '\r' | sed -n '/^{/,/^}/p' >"$OUT/${name}_verify.json"
    local verify_exit=$?
    grep '"ok"' "$OUT/${name}_verify.json"
    RESULTS+=("$name locust_exit=$locust_exit verify_exit=$verify_exit")
}

journey() {
    local name=$1 users=$2
    shift 2
    local event
    event=$(seed --scenario journey) || stop "could not seed $name"
    run "$name" journey.py "$users" 10 "$JOURNEY_TIME" "$event" "$(utc_now)" "$@"
}

scenario_p1() {
    local event
    # The sale opens 420 s after seeding, which leaves 1,000 buyers time to sign in.
    event=$(seed --scenario flash --opens-in 420) || stop "could not seed p1"
    run p1 flash_sale.py 1000 5 9m "$event" "$(utc_now)" LOADTEST_SUMMARY="$OUT/p1_summary.json"
}

scenario_journey() { journey journey 200; }

scenario_r1() {
    faults 0 0.0 0.5 0.0
    journey r1_duplicate_webhooks 100
    no_faults
}

scenario_r2() { journey r2_replays 100 LOADTEST_REPLAY_RATE=0.3; }

scenario_r3() {
    faults 2000 1.0 0.0 0.0
    journey r3_gateway_errors 100
    no_faults
    log "Waiting 60 s for the circuit breakers to close"
    sleep 60
}

scenario_r4() {
    faults 6000 0.0 0.0 0.0
    journey r4_gateway_timeouts 100
    no_faults
    log "Waiting 60 s for the circuit breakers to close"
    sleep 60
}

scenario_r5() {
    faults 0 0.0 0.0 0.2
    journey r5_dropped_webhooks 100
    no_faults
}

# Restarts worker-critical about three minutes into a duplicate-webhook run.
scenario_r6() {
    local event
    faults 0 0.0 0.5 0.0
    event=$(seed --scenario journey) || stop "could not seed r6_worker_restart"
    (sleep 180 && log "R6: restarting worker-critical" && railway restart -s worker-critical -y) &
    run r6_worker_restart journey.py 100 10 "$JOURNEY_TIME" "$event" "$(utc_now)"
    no_faults
}

check() {
    log "Locust: $("$LOCUST" --version)"
    log "Railway SSH to web:"
    manage seed_loadtest --help | head -n 1
    log "Railway SSH to worker-bulk:"
    remote worker-bulk /opt/venv/bin/python manage.py loadtest_sample --help | head -n 1
    log "Current faults (read only):"
    django_exec "from mockgateway.models import FaultConfig
config = FaultConfig.load()
print('FAULTS', config.latency_ms, config.error_rate, config.duplicate_webhook_rate, config.drop_webhook_rate)"
    log "Check finished. Every step above should print a line without an error."
}

on_exit() {
    local jobs_left
    jobs_left=$(jobs -p)
    [ -n "$jobs_left" ] && kill $jobs_left 2>/dev/null
    set_faults 0 0.0 0.0 0.0 || log "WARNING: faults were not reset; run bash run_all.sh reset"
}

case "${1:-}" in
    check)
        check
        exit
        ;;
    reset)
        set_faults 0 0.0 0.0 0.0
        exit
        ;;
esac

cleanup=false
if [ "${1:-}" = --cleanup ]; then
    cleanup=true
    shift
fi
scenarios=("$@")
[ ${#scenarios[@]} -gt 0 ] || scenarios=("${ALL_SCENARIOS[@]}")
for scenario in "${scenarios[@]}"; do
    declare -F "scenario_$scenario" >/dev/null || stop "unknown scenario $scenario; choose from ${ALL_SCENARIOS[*]}"
done

mkdir -p "$OUT"
exec > >(tee -a "$OUT/run_all.log") 2>&1
trap on_exit EXIT
log "Results go to $OUT; scenarios: ${scenarios[*]}"
no_faults

for scenario in "${scenarios[@]}"; do
    "scenario_$scenario"
done

if $cleanup; then
    log "Cleanup: waiting 300 s for abandoned holds to be swept"
    sleep 300
    manage purge_mockdata --yes
    manage seed_mockdata
fi

log "Summary (exit 0 = passed; Locust exits 1 on any failed request, including expected ones in R3 to R5)"
printf '%s\n' "${RESULTS[@]}" | tee "$OUT/summary.txt"
