#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/infra/docker-compose.dev.yml}"
PYTHON_BIN="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"

WITH_BOT=0
WITH_DIGEST=0
RUN_SMOKE=0
REBUILD=0
FOLLOW_LOGS=0
SYNC_ENV=1

usage() {
  cat <<'USAGE'
Usage: scripts/local_up.sh [options]

Starts the full local Skillra Docker baseline:
postgres, redis, meilisearch, minio, minio-init, migrator, API, and web.

Options:
  --with-bot       Start Telegram bot too (requires non-placeholder token).
  --with-digest    Start digest worker too.
  --smoke          Run strict API/search/storage smoke after startup.
  --rebuild        Rebuild local Docker images before startup.
  --logs           Follow logs after successful startup.
  --no-sync-env    Do not merge missing schema defaults into .env.
  -h, --help       Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-bot) WITH_BOT=1 ;;
    --with-digest) WITH_DIGEST=1 ;;
    --smoke) RUN_SMOKE=1 ;;
    --rebuild) REBUILD=1 ;;
    --logs) FOLLOW_LOGS=1 ;;
    --no-sync-env) SYNC_ENV=0 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "[local-up] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[local-up] ${ENV_FILE} is missing; rendering from env schema"
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/env_render.py" --profile local --output "${ENV_FILE}"
elif [[ "${SYNC_ENV}" -eq 1 ]]; then
  echo "[local-up] Synchronizing ${ENV_FILE} with env schema while preserving existing values"
  tmp_env="$(mktemp)"
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/env_render.py" --profile local --merge-env-file "${ENV_FILE}" --output "${tmp_env}"
  mv "${tmp_env}" "${ENV_FILE}"
fi

"${PYTHON_BIN}" "${REPO_ROOT}/scripts/env_doctor.py" --profile local --env-file "${ENV_FILE}"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

API_PORT="${SKILLRA_API_PORT:-8000}"
WEB_PORT="${SKILLRA_WEB_PORT:-5173}"
MEILI_PORT="${MEILISEARCH_PORT:-7700}"
MINIO_PORT_VALUE="${MINIO_PORT:-9000}"
MINIO_CONSOLE_PORT_VALUE="${MINIO_CONSOLE_PORT:-9001}"
API_BASE_URL="http://localhost:${API_PORT}"
WEB_URL="http://localhost:${WEB_PORT}"

mkdir -p "${REPO_ROOT}/data/processed" "${REPO_ROOT}/data/raw/hh"

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts="${3:-90}"

  echo "[local-up] Waiting for ${label}: ${url}"
  for _attempt in $(seq 1 "${attempts}"); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      echo "[local-up] ${label} is ready"
      return 0
    fi
    sleep 2
  done

  echo "[local-up] ${label} did not become ready in time" >&2
  compose ps >&2 || true
  compose logs --tail=160 skillra-api skillra-web postgres redis meilisearch minio minio-init migrator >&2 || true
  return 1
}

echo "[local-up] Validating compose configuration"
compose config -q

CORE_SERVICES=(postgres redis meilisearch minio minio-init migrator skillra-api skillra-web)
echo "[local-up] Starting full local baseline: ${CORE_SERVICES[*]}"
if [[ "${REBUILD}" -eq 1 ]]; then
  compose up -d --build "${CORE_SERVICES[@]}"
else
  compose up -d "${CORE_SERVICES[@]}"
fi

if [[ "${WITH_DIGEST}" -eq 1 ]]; then
  echo "[local-up] Starting digest worker"
  if [[ "${REBUILD}" -eq 1 ]]; then
    compose --profile digest up -d --build digest-worker
  else
    compose --profile digest up -d digest-worker
  fi
fi

if [[ "${WITH_BOT}" -eq 1 ]]; then
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || "${TELEGRAM_BOT_TOKEN:-}" == changeme-* ]]; then
    echo "[local-up] --with-bot requested, but TELEGRAM_BOT_TOKEN is empty or placeholder" >&2
    exit 1
  fi
  echo "[local-up] Starting Telegram bot"
  if [[ "${REBUILD}" -eq 1 ]]; then
    compose up -d --build skillra-bot
  else
    compose up -d skillra-bot
  fi
fi

wait_for_url "${API_BASE_URL}/health" "API liveness"
wait_for_url "${API_BASE_URL}/v1/health" "API readiness"
wait_for_url "${WEB_URL}" "Web"
wait_for_url "http://localhost:${MEILI_PORT}/health" "MeiliSearch"
wait_for_url "http://localhost:${MINIO_PORT_VALUE}/minio/health/live" "MinIO API"
wait_for_url "http://localhost:${MINIO_CONSOLE_PORT_VALUE}" "MinIO Console"

if [[ "${RUN_SMOKE}" -eq 1 ]]; then
  echo "[local-up] Running strict API/search/storage smoke"
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/smoke_skillra_platform.py" \
    --base-url "${API_BASE_URL}" \
    --token "${SKILLRA_API_TOKEN}" \
    --admin-token "${SKILLRA_ADMIN_TOKEN}" \
    --sprint12-checks strict \
    --search-index-checks strict \
    --storage-checks strict
fi

cat <<EOF
[local-up] Skillra local baseline is running.

Web:           ${WEB_URL}
API:           ${API_BASE_URL}
API docs:      ${API_BASE_URL}/docs
API readiness: ${API_BASE_URL}/v1/health
MeiliSearch:   http://localhost:${MEILI_PORT}/health
MinIO Console: http://localhost:${MINIO_CONSOLE_PORT_VALUE}

Useful commands:
  make health-local
  make local-smoke
  make local-down
EOF

if [[ "${FOLLOW_LOGS}" -eq 1 ]]; then
  compose logs -f
fi
