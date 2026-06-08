#!/usr/bin/env sh
set -eu

interval_seconds="${PRICE_INVENTORY_UPDATE_INTERVAL_SECONDS:-3600}"
initial_delay_seconds="${PRICE_INVENTORY_UPDATE_INITIAL_DELAY_SECONDS:-0}"

if [ "${initial_delay_seconds}" -gt 0 ]; then
  echo "Delaying first price/inventory update by ${initial_delay_seconds}s"
  sleep "${initial_delay_seconds}"
fi

while true; do
  started_at="$(date -Iseconds)"
  echo "[${started_at}] Starting delayed Amazon price/inventory confirmation"

  if python main.py --task confirm-price-inventory-api --no-dry-run; then
    echo "[$(date -Iseconds)] Delayed price/inventory confirmation completed"
  else
    status=$?
    echo "[$(date -Iseconds)] Delayed price/inventory confirmation failed with exit code ${status}"
  fi

  echo "[${started_at}] Starting hourly Amazon price/inventory update"

  if python main.py --task update-price-inventory-api --no-dry-run; then
    echo "[$(date -Iseconds)] Price/inventory update completed"
  else
    status=$?
    echo "[$(date -Iseconds)] Price/inventory update failed with exit code ${status}"
  fi

  echo "Sleeping ${interval_seconds}s before next price/inventory update"
  sleep "${interval_seconds}"
done
