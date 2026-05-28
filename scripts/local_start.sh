#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/infra/docker-compose.dev.yml}"

WITH_BOT=0
RUN_SMOKE=0
REBUILD=0
DETACHED=1

usage() {
  cat <<'USAGE'
Usage: scripts/local_start.sh [options]

Starts the local Skillra app using the existing .env file.

Options:
  --with-bot    Also start Telegram bot service.
  --smoke       Run API smoke checks after startup.
  --rebuild     Rebuild Docker images before starting services.
  --logs        Follow compose logs after successful startup.
  -h, --help    Show this help.

Environment overrides:
  ENV_FILE      Path to env file. Default: .env
  COMPOSE_FILE  Path to compose file. Default: infra/docker-compose.dev.yml
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-bot)
      WITH_BOT=1
      ;;
    --smoke)
      RUN_SMOKE=1
      ;;
    --rebuild)
      REBUILD=1
      ;;
    --logs)
      DETACHED=0
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "[local-start] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[local-start] Env file not found: ${ENV_FILE}" >&2
  echo "[local-start] Create it first, for example: cp .env.example .env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

API_PORT="${SKILLRA_API_PORT:-8000}"
API_BASE_URL="http://localhost:${API_PORT}"
WEB_URL="http://localhost:5173"
SERVICE_TOKEN="${SKILLRA_API_TOKEN:-}"

if [[ -z "${SERVICE_TOKEN}" ]]; then
  echo "[local-start] SKILLRA_API_TOKEN is required in ${ENV_FILE}" >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/data/processed" "${REPO_ROOT}/data/raw/hh"

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempts="${3:-90}"

  echo "[local-start] Waiting for ${label}: ${url}"
  for attempt in $(seq 1 "${attempts}"); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      echo "[local-start] ${label} is ready"
      return 0
    fi
    sleep 2
  done

  echo "[local-start] ${label} did not become ready in time" >&2
  compose ps >&2 || true
  echo "[local-start] Recent logs:" >&2
  compose logs --tail=120 skillra-api skillra-web postgres redis migrator >&2 || true
  return 1
}

echo "[local-start] Using env file: ${ENV_FILE}"
echo "[local-start] Validating compose configuration"
compose config -q

CORE_SERVICES=(postgres redis migrator skillra-api skillra-web)

echo "[local-start] Starting core services: ${CORE_SERVICES[*]}"
if [[ "${REBUILD}" -eq 1 ]]; then
  compose up -d --build "${CORE_SERVICES[@]}"
else
  compose up -d "${CORE_SERVICES[@]}"
fi

if [[ "${WITH_BOT}" -eq 1 ]]; then
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || "${TELEGRAM_BOT_TOKEN:-}" == changeme-* ]]; then
    echo "[local-start] --with-bot requested, but TELEGRAM_BOT_TOKEN is empty or placeholder in ${ENV_FILE}" >&2
    exit 1
  fi
  echo "[local-start] Starting Telegram bot"
  if [[ "${REBUILD}" -eq 1 ]]; then
    compose up -d --build skillra-bot
  else
    compose up -d skillra-bot
  fi
fi

wait_for_url "${API_BASE_URL}/health" "API"
wait_for_url "${WEB_URL}" "Web"

if [[ "${RUN_SMOKE}" -eq 1 ]]; then
  echo "[local-start] Running API smoke checks"
  compose exec -T skillra-api python scripts/smoke_skillra_platform.py \
    --base-url "http://127.0.0.1:${API_PORT}" \
    --token "${SERVICE_TOKEN}"
fi

cat <<EOF
[local-start] Skillra is running.

API: ${API_BASE_URL}
API health: ${API_BASE_URL}/health
Web: ${WEB_URL}
Service token for UI/API checks: ${SERVICE_TOKEN}

Useful commands:
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" logs -f
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down
EOF

if [[ "${DETACHED}" -eq 0 ]]; then
  compose logs -f
fi
