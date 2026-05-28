#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/infra/docker-compose.dev.yml}"
SMOKE_SCRIPT="${REPO_ROOT}/scripts/smoke_skillra_platform.py"
DATA_DIR="${REPO_ROOT}/data/processed"
LATEST_DIR="${DATA_DIR}/latest"
HH_FEATURES_PARQUET="${LATEST_DIR}/hh_features.parquet"
MARKET_VIEW_PARQUET="${LATEST_DIR}/market_view.parquet"
LEGACY_FEATURES_PARQUET="${DATA_DIR}/hh_features.parquet"
LEGACY_MARKET_VIEW_PARQUET="${DATA_DIR}/market_view.parquet"
PYTHON_BIN="${PYTHON:-python3}"
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
fi

ensure_data() {
  if [[ -f "${HH_FEATURES_PARQUET}" && -f "${MARKET_VIEW_PARQUET}" ]]; then
    echo "[compose-smoke] Required parquet files already present."
    return
  fi
  if [[ -f "${LEGACY_FEATURES_PARQUET}" && -f "${LEGACY_MARKET_VIEW_PARQUET}" ]]; then
    echo "[compose-smoke] Found legacy processed parquet files; proceeding without regeneration."
    return
  fi
  if [[ ! -f "${HH_FEATURES_PARQUET}" || ! -f "${MARKET_VIEW_PARQUET}" ]]; then
    echo "[compose-smoke] Processed parquet files missing. Running pipeline to generate data."
    "${PYTHON_BIN}" "${REPO_ROOT}/scripts/run_pipeline.py"
  else
    echo "[compose-smoke] Required parquet files already present."
  fi
}

cleanup() {
  set +e
  echo "[compose-smoke] Bringing down docker-compose stack"
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down >/dev/null
}
trap cleanup EXIT

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -n "${SMOKE_API_PORT:-}" ]]; then
  export SKILLRA_API_PORT="${SMOKE_API_PORT}"
fi
if [[ -n "${SMOKE_POSTGRES_PORT:-}" ]]; then
  export POSTGRES_PORT="${SMOKE_POSTGRES_PORT}"
fi
if [[ -n "${SMOKE_REDIS_PORT:-}" ]]; then
  export REDIS_PORT="${SMOKE_REDIS_PORT}"
fi
if [[ -n "${SMOKE_MEILISEARCH_PORT:-}" ]]; then
  export MEILISEARCH_PORT="${SMOKE_MEILISEARCH_PORT}"
fi
if [[ -n "${SMOKE_MINIO_PORT:-}" ]]; then
  export MINIO_PORT="${SMOKE_MINIO_PORT}"
fi
if [[ -n "${SMOKE_MINIO_CONSOLE_PORT:-}" ]]; then
  export MINIO_CONSOLE_PORT="${SMOKE_MINIO_CONSOLE_PORT}"
fi

BASE_URL="${SMOKE_BASE_URL:-${SKILLRA_API_BASE_URL:-http://localhost:${SKILLRA_API_PORT:-8000}}}"
HEALTH_URL="${BASE_URL%/}/health"
SERVICE_TOKEN="${SKILLRA_API_TOKEN:-}"
ADMIN_TOKEN="${SKILLRA_ADMIN_TOKEN:-}"

if [[ -z "${SERVICE_TOKEN}" ]]; then
  echo "[compose-smoke] SKILLRA_API_TOKEN is required. Populate it in ${ENV_FILE} or export it before running." >&2
  exit 1
fi
if [[ -z "${ADMIN_TOKEN}" ]]; then
  echo "[compose-smoke] SKILLRA_ADMIN_TOKEN is required for strict search smoke checks. Populate it in ${ENV_FILE} or export it before running." >&2
  exit 1
fi

ensure_data

echo "[compose-smoke] Applying migrations"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile migrate run --build --rm migrator

echo "[compose-smoke] Starting docker-compose stack"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --build skillra-api

echo "[compose-smoke] Waiting for API health"
READINESS_URLS=("${BASE_URL%/}/v1/health" "${HEALTH_URL}")
for attempt in $(seq 1 60); do
  for readiness_url in "${READINESS_URLS[@]}"; do
    if curl -fsS "${readiness_url}" >/dev/null 2>&1; then
      echo "[compose-smoke] API is healthy at ${readiness_url}"
      READY=1
      break 2
    fi
  done
  sleep 2
done

if [[ -z "${READY:-}" ]]; then
  echo "[compose-smoke] API failed to become healthy at any readiness endpoint (${READINESS_URLS[*]})" >&2
  exit 1
fi

echo "[compose-smoke] Running smoke script"
"${PYTHON_BIN}" "${SMOKE_SCRIPT}" \
  --base-url "${BASE_URL}" \
  --token "${SERVICE_TOKEN}" \
  --admin-token "${ADMIN_TOKEN}" \
  --sprint12-checks strict \
  --search-index-checks strict \
  --storage-checks strict

echo "[compose-smoke] Smoke checks completed successfully"
