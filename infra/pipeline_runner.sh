#!/usr/bin/env bash
set -euo pipefail

cd /workspace

require_env_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "[pipeline-runner] ${name} is required to call /v1/admin/reload-data" >&2
    exit 1
  fi
}

require_env_var "SKILLRA_API_BASE_URL"
require_env_var "SKILLRA_API_TOKEN"
require_env_var "SKILLRA_ADMIN_TOKEN"

API_BASE_URL="${SKILLRA_API_BASE_URL%/}"
SKILLRA_API_TOKEN="${SKILLRA_API_TOKEN}"
SKILLRA_ADMIN_TOKEN="${SKILLRA_ADMIN_TOKEN}"
DATA_RUN_ID="${SKILLRA_DATA_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
DATA_RUN_COMPLETED=0
hh_storage_dir="${HH_STORAGE_DIR:-data/raw/hh}"
raw_quality_report_path="${hh_storage_dir}/raw_quality_report.json"

pipeline_args=()
pipeline_args+=(--run-id "${DATA_RUN_ID}")

update_data_run_state() {
  local state="$1"
  post_data_run_payload "{\"state\":\"${state}\",\"source\":\"pipeline_runner\"}"
}

post_data_run_payload() {
  local payload="$1"
  local url="${API_BASE_URL}/v1/admin/data-runs/${DATA_RUN_ID}/state"
  local curl_state_args=(
    -sS
    -X POST
    "${url}"
    -H "X-Skillra-Token: ${SKILLRA_API_TOKEN}"
    -H "X-Admin-Token: ${SKILLRA_ADMIN_TOKEN}"
    -H "Content-Type: application/json"
    -d "${payload}"
  )

  if curl --help all 2>&1 | grep -q -- '--fail-with-body'; then
    curl_state_args+=(--fail-with-body)
  else
    curl_state_args+=(-f)
  fi

  curl "${curl_state_args[@]}" >/dev/null
}

current_active_data_run_id() {
  local url="${API_BASE_URL}/v1/admin/data-runs/active"
  local response
  response="$(
    curl -sSf \
      "${url}" \
      -H "X-Skillra-Token: ${SKILLRA_API_TOKEN}" \
      -H "X-Admin-Token: ${SKILLRA_ADMIN_TOKEN}" || true
  )"
  if [[ -z "${response}" ]]; then
    return 0
  fi
  printf '%s' "${response}" | python -c 'import json, sys; payload=json.load(sys.stdin); active=payload.get("active") or {}; print(active.get("run_id") or "")'
}

activate_data_run_pointer() {
  local run_id="$1"
  if [[ -z "${run_id}" ]]; then
    return 0
  fi
  local url="${API_BASE_URL}/v1/admin/data-runs/${run_id}/activate"
  curl -sSf \
    -X POST \
    "${url}" \
    -H "X-Skillra-Token: ${SKILLRA_API_TOKEN}" \
    -H "X-Admin-Token: ${SKILLRA_ADMIN_TOKEN}" \
    >/dev/null
}

build_data_run_payload_from_processed_artifacts() {
  local state="$1"
  local dataset_meta_path="data/processed/runs/${DATA_RUN_ID}/dataset_meta.json"
  local quality_report_path="data/processed/runs/${DATA_RUN_ID}/quality_report.json"
  local run_manifest_path="data/processed/runs/${DATA_RUN_ID}/run_manifest.json"
  DATA_RUN_PAYLOAD_STATE="${state}" \
  DATA_RUN_PAYLOAD_SOURCE="pipeline_runner" \
  DATA_RUN_PAYLOAD_META_PATH="${dataset_meta_path}" \
  DATA_RUN_PAYLOAD_QUALITY_PATH="${quality_report_path}" \
  DATA_RUN_PAYLOAD_MANIFEST_PATH="${run_manifest_path}" \
  DATA_RUN_PAYLOAD_RAW_QUALITY_PATH="${raw_quality_report_path:-}" \
  DATA_RUN_PAYLOAD_S3_BUCKET_PROCESSED="${S3_BUCKET_PROCESSED:-}" \
  DATA_RUN_PAYLOAD_S3_SYNC="${SKILLRA_S3_SYNC:-0}" \
    python - <<'PY'
import json
import os
from pathlib import Path


def load_json(path: str | None) -> dict | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


state = os.environ["DATA_RUN_PAYLOAD_STATE"]
source = os.environ["DATA_RUN_PAYLOAD_SOURCE"]
meta_path = os.environ["DATA_RUN_PAYLOAD_META_PATH"]
quality_path = os.environ["DATA_RUN_PAYLOAD_QUALITY_PATH"]
manifest_path = os.environ["DATA_RUN_PAYLOAD_MANIFEST_PATH"]
raw_quality_path = os.environ.get("DATA_RUN_PAYLOAD_RAW_QUALITY_PATH") or None
bucket = os.environ.get("DATA_RUN_PAYLOAD_S3_BUCKET_PROCESSED") or None
s3_sync = os.environ.get("DATA_RUN_PAYLOAD_S3_SYNC") == "1"

meta = load_json(meta_path) or {}
quality = load_json(quality_path) or {}
manifest = load_json(manifest_path) or {}
raw_quality = load_json(raw_quality_path)
ingestion = meta.get("ingestion") if isinstance(meta.get("ingestion"), dict) else {}
run_id = meta.get("run_id") or os.environ.get("SKILLRA_DATA_RUN_ID") or ""

if s3_sync and bucket:
    manifest_uri = f"s3://{bucket}/hh/manifests/run={run_id}/manifest.json"
    quality_uri = f"s3://{bucket}/hh/manifests/run={run_id}/quality_report.json"
else:
    manifest_uri = manifest_path
    quality_uri = quality_path

payload = {
    "state": state,
    "source": source,
    "raw_rows": ingestion.get("row_count"),
    "processed_rows": meta.get("features_rows"),
    "dataset_meta_path": meta_path,
    "manifest_uri": manifest_uri,
    "quality_report_uri": quality_uri,
    "artifact_uris": {"artifacts": manifest.get("artifacts", [])},
    "raw_quality_report": raw_quality,
    "processed_quality_report": meta.get("processed_quality_report") or quality.get("processed"),
    "product_eligibility": meta.get("product_eligibility"),
    "source_capability_ref": meta.get("source_capability_ref"),
}
print(json.dumps({key: value for key, value in payload.items() if value is not None}, ensure_ascii=False))
PY
}

mark_data_run_failed_on_exit() {
  local exit_code=$?
  if [[ "${exit_code}" -ne 0 && "${DATA_RUN_COMPLETED}" != "1" ]]; then
    update_data_run_state failed || true
  fi
}

trap mark_data_run_failed_on_exit EXIT

if [[ "${SKILLRA_REFRESH_HH:-}" == "1" ]]; then
  hh_lockfile="${hh_storage_dir}/.refresh.lock"
  mkdir -p "${hh_storage_dir}"
  exec 9>"${hh_lockfile}"
  if ! flock -n 9; then
    echo "[pipeline-runner] HH daily refresh already running (lock: ${hh_lockfile}); exiting."
    exit 0
  fi
  update_data_run_state collecting
  hh_args=(--storage-dir "${hh_storage_dir}")

  if [[ -n "${HH_QUERY:-}" ]]; then
    hh_args+=(--query "${HH_QUERY}")
  fi

  if [[ -n "${HH_LIMIT:-}" ]]; then
    hh_args+=(--limit "${HH_LIMIT}")
  fi

  if [[ "${HH_SALARY_ONLY:-0}" == "1" ]]; then
    hh_args+=(--salary-only)
  else
    hh_args+=(--no-salary-only)
  fi

  echo "[pipeline-runner] Running HH daily refresh..."
  python scripts/hh_daily_refresh.py "${hh_args[@]}"
  echo "[pipeline-runner] Validating raw HH artifacts..."
  python scripts/raw_hh_gate.py --storage-dir "${hh_storage_dir}" --report-path "${raw_quality_report_path}"

  if [[ "${SKILLRA_S3_SYNC:-}" == "1" ]]; then
    echo "[pipeline-runner] Syncing raw HH data to S3..."
    python scripts/s3_sync_raw_hh.py --storage-dir "${hh_storage_dir}"
    update_data_run_state raw_committed
    echo "[pipeline-runner] Verifying raw HH data in S3..."
    python scripts/raw_hh_gate.py --storage-dir "${hh_storage_dir}" --require-s3 --report-path "${raw_quality_report_path}"
  elif [[ "${SKILLRA_REQUIRE_RAW_S3_COMMIT:-}" == "1" ]]; then
    echo "[pipeline-runner] SKILLRA_REQUIRE_RAW_S3_COMMIT=1 but SKILLRA_S3_SYNC is not enabled; refusing to process unpublished raw HH." >&2
    exit 1
  fi
  update_data_run_state raw_validated

  pipeline_args+=(
    --raw-data-file "${hh_storage_dir}/latest.csv"
    --dataset-meta-extra "${hh_storage_dir}/state.json"
    --raw-quality-report "${raw_quality_report_path}"
  )
elif [[ "${SKILLRA_USE_RAW_HH_LATEST:-}" == "1" ]]; then
  echo "[pipeline-runner] Using existing raw HH latest from ${hh_storage_dir}"
  echo "[pipeline-runner] Validating raw HH artifacts..."
  python scripts/raw_hh_gate.py --storage-dir "${hh_storage_dir}" --report-path "${raw_quality_report_path}"

  if [[ "${SKILLRA_S3_SYNC:-}" == "1" ]]; then
    echo "[pipeline-runner] Syncing raw HH data to S3..."
    python scripts/s3_sync_raw_hh.py --storage-dir "${hh_storage_dir}"
    update_data_run_state raw_committed
    echo "[pipeline-runner] Verifying raw HH data in S3..."
    python scripts/raw_hh_gate.py --storage-dir "${hh_storage_dir}" --require-s3 --report-path "${raw_quality_report_path}"
  elif [[ "${SKILLRA_REQUIRE_RAW_S3_COMMIT:-}" == "1" ]]; then
    echo "[pipeline-runner] Verifying existing raw HH data in S3..."
    python scripts/raw_hh_gate.py --storage-dir "${hh_storage_dir}" --require-s3 --report-path "${raw_quality_report_path}"
  fi
  update_data_run_state raw_validated

  pipeline_args+=(
    --raw-data-file "${hh_storage_dir}/latest.csv"
    --dataset-meta-extra "${hh_storage_dir}/state.json"
    --raw-quality-report "${raw_quality_report_path}"
  )
fi

echo "[pipeline-runner] Running data pipeline..."
update_data_run_state processing
python scripts/run_pipeline.py "${pipeline_args[@]}"

if [[ "${SKILLRA_S3_SYNC:-}" == "1" ]]; then
  echo "[pipeline-runner] Syncing processed data to S3..."
  python scripts/s3_sync_processed.py
fi
processed_payload="$(build_data_run_payload_from_processed_artifacts processed_validated)"
post_data_run_payload "${processed_payload}"
update_data_run_state staged

RELOAD_URL="${API_BASE_URL}/v1/admin/reload-data"
echo "[pipeline-runner] Triggering API data reload at ${RELOAD_URL}"
update_data_run_state indexing
previous_active_run_id="$(current_active_data_run_id)"
published_payload="$(build_data_run_payload_from_processed_artifacts published)"
post_data_run_payload "${published_payload}"

curl_args=(
  -sS
  -X POST
  "${RELOAD_URL}"
  -H "X-Skillra-Token: ${SKILLRA_API_TOKEN}"
  -H "X-Admin-Token: ${SKILLRA_ADMIN_TOKEN}"
)

if curl --help all 2>&1 | grep -q -- '--fail-with-body'; then
  curl_args+=(--fail-with-body)
fi

response="$(
  curl "${curl_args[@]}" -w '\n%{http_code}' || true
)"

status="${response##*$'\n'}"
body="${response%$'\n'*}"

if [[ ! "${status}" =~ ^2[0-9]{2}$ ]]; then
  printf '[pipeline-runner] Reload endpoint returned HTTP %s:\n%s\n' "${status}" "${body}" >&2
  if [[ -n "${previous_active_run_id}" ]]; then
    echo "[pipeline-runner] Rolling active dataset pointer back to ${previous_active_run_id}" >&2
    activate_data_run_pointer "${previous_active_run_id}" || true
  fi
  exit 1
fi

printf '[pipeline-runner] Reload triggered successfully (status %s). Response: %s\n' "${status}" "${body}"
reloaded_run_id="$(printf '%s' "${body}" | python -c 'import json, sys; print((json.load(sys.stdin) or {}).get("dataset_run_id") or "")')"
if [[ "${reloaded_run_id}" != "${DATA_RUN_ID}" ]]; then
  printf '[pipeline-runner] Reload dataset_run_id mismatch: got %s expected %s\n' "${reloaded_run_id}" "${DATA_RUN_ID}" >&2
  if [[ -n "${previous_active_run_id}" ]]; then
    echo "[pipeline-runner] Rolling active dataset pointer back to ${previous_active_run_id}" >&2
    activate_data_run_pointer "${previous_active_run_id}" || true
  fi
  exit 1
fi

if [[ "${SKILLRA_S3_SYNC:-}" == "1" ]]; then
  echo "[pipeline-runner] Mirroring active dataset pointer to S3..."
  python scripts/s3_sync_processed.py --publish-active-pointer || \
    echo "[pipeline-runner] WARNING: failed to mirror active dataset pointer to S3; Postgres active pointer remains authoritative." >&2
fi
DATA_RUN_COMPLETED=1

# Sprint-009 TASK-07: Notify subscribers about market data update
NOTIFY_URL="${API_BASE_URL}/v1/admin/notify-data-updated"
echo "[pipeline-runner] Notifying subscribers about market data update..."
curl -sS -X POST "${NOTIFY_URL}" \
  -H "X-Skillra-Token: ${SKILLRA_API_TOKEN}" \
  -H "X-Admin-Token: ${SKILLRA_ADMIN_TOKEN}" || true

metrics_dir="/workspace/data/metrics"
metrics_file="${metrics_dir}/skillra_pipeline_last_success.prom"
metrics_tmp="${metrics_file}.tmp"
metrics_ts="$(date +%s)"

mkdir -p "${metrics_dir}"
printf 'skillra_pipeline_last_success_timestamp_seconds %s\n' "${metrics_ts}" > "${metrics_tmp}"
mv "${metrics_tmp}" "${metrics_file}"

echo "[pipeline-runner] Completed"
