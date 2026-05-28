#!/usr/bin/env bash
set -euo pipefail

cd /workspace

schedule_hour="${DATA_SCHEDULER_UTC_HOUR:-2}"
schedule_minute="${DATA_SCHEDULER_UTC_MINUTE:-0}"
max_retries="${DATA_SCHEDULER_MAX_RETRIES:-3}"
retry_delay="${DATA_SCHEDULER_RETRY_DELAY_SECONDS:-60}"

next_sleep_seconds() {
  python - "$schedule_hour" "$schedule_minute" <<'PY'
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys

hour = int(sys.argv[1])
minute = int(sys.argv[2])
now = datetime.now(timezone.utc)
target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
if target <= now:
    target += timedelta(days=1)
print(max(1, int((target - now).total_seconds())))
PY
}

run_pipeline_with_retries() {
  local attempt
  local status

  for attempt in $(seq 1 "${max_retries}"); do
    echo "[data-scheduler] Starting scheduled pipeline attempt ${attempt}/${max_retries}"
    if bash infra/pipeline_runner.sh; then
      echo "[data-scheduler] Scheduled pipeline run completed on attempt ${attempt}"
      return 0
    else
      status="$?"
    fi
    if [ "${attempt}" -lt "${max_retries}" ]; then
      echo "[data-scheduler] Pipeline attempt ${attempt} failed with status ${status}; retrying in ${retry_delay}s" >&2
      sleep "${retry_delay}"
    else
      echo "[data-scheduler] Pipeline FAILED after ${max_retries} attempts; status ${status}" >&2
    fi
  done

  return "${status:-1}"
}

echo "[data-scheduler] Daily pipeline schedule: ${schedule_hour}:${schedule_minute} UTC"
echo "[data-scheduler] Retry policy: ${max_retries} attempts, ${retry_delay}s delay"

while true; do
  sleep_seconds="$(next_sleep_seconds)"
  echo "[data-scheduler] Sleeping ${sleep_seconds}s until next run"
  sleep "${sleep_seconds}"

  echo "[data-scheduler] Starting scheduled pipeline run"
  if run_pipeline_with_retries; then
    echo "[data-scheduler] Scheduled pipeline run succeeded; pipeline_runner handled reload and notification"
  else
    status="$?"
    echo "[data-scheduler] Scheduled pipeline run failed after retries with status ${status}" >&2
  fi
done
