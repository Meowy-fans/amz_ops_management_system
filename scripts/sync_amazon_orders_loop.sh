#!/usr/bin/env sh
set -eu

interval_seconds="${AMAZON_ORDER_SYNC_INTERVAL_SECONDS:-1800}"
initial_delay_seconds="${AMAZON_ORDER_SYNC_INITIAL_DELAY_SECONDS:-60}"

if [ "${initial_delay_seconds}" -gt 0 ]; then
  echo "Delaying first Amazon order sync by ${initial_delay_seconds}s"
  sleep "${initial_delay_seconds}"
fi

while true; do
  started_at="$(date -Iseconds)"
  echo "[${started_at}] Starting Amazon order sync"

  if python main.py --task sync-amazon-orders; then
    echo "[$(date -Iseconds)] Amazon order sync completed"
  else
    status=$?
    echo "[$(date -Iseconds)] Amazon order sync failed with exit code ${status}"
  fi

  echo "Sleeping ${interval_seconds}s before next Amazon order sync"
  sleep "${interval_seconds}"
done
