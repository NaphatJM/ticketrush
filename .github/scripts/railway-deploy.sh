#!/usr/bin/env bash
# Usage: railway-deploy.sh <service> <commit-sha>
# Deploys the repository to one Railway service and returns only once that deployment is live.
set -euo pipefail

service="$1"
sha="$2"
timeout_seconds=600

railway up . --service "$service" --ci --message "$sha"

# `railway up --ci` can return when the build finishes, before the new deployment serves traffic.
deadline=$((SECONDS + timeout_seconds))
while :; do
  status=$(railway deployment list --service "$service" --json --limit 1 | jq -r '.[0].status // empty')
  case "$status" in
    SUCCESS)
      echo "$service is live"
      exit 0
      ;;
    FAILED | CRASHED | REMOVED | REMOVING)
      echo "::error::$service deployment ended as $status"
      exit 1
      ;;
    "")
      echo "::error::could not read the $service deployment status"
      exit 1
      ;;
  esac
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error::$service was not live after ${timeout_seconds}s (last status $status)"
    exit 1
  fi
  echo "$service: $status"
  sleep 10
done
