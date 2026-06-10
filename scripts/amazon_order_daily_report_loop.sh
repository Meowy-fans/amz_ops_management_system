#!/usr/bin/env sh
set -eu

report_hour="${AMAZON_ORDER_DAILY_REPORT_HOUR:-9}"
report_minute="${AMAZON_ORDER_DAILY_REPORT_MINUTE:-0}"
tz="${AMAZON_ORDER_DAILY_REPORT_TZ:-Asia/Shanghai}"

while true; do
  sleep_seconds="$(python - <<'PY'
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

tz = ZoneInfo(os.environ.get("AMAZON_ORDER_DAILY_REPORT_TZ", "Asia/Shanghai"))
hour = int(os.environ.get("AMAZON_ORDER_DAILY_REPORT_HOUR", "9"))
minute = int(os.environ.get("AMAZON_ORDER_DAILY_REPORT_MINUTE", "0"))

now = datetime.now(tz)
target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
if now >= target:
    target += timedelta(days=1)
print(int((target - now).total_seconds()))
PY
)"
  echo "Sleeping ${sleep_seconds}s until next daily order report (${tz} ${report_hour}:$(printf '%02d' "${report_minute}"))"
  sleep "${sleep_seconds}"

  started_at="$(date -Iseconds)"
  echo "[${started_at}] Starting Amazon order daily report"
  if python main.py --task amazon-order-daily-report; then
    echo "[$(date -Iseconds)] Amazon order daily report completed"
  else
    status=$?
    echo "[$(date -Iseconds)] Amazon order daily report failed with exit code ${status}"
  fi
done
