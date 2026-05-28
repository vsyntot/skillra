#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROFILE=local
HOST=""
USER_NAME="${DEPLOY_USER:-root}"
REPO_PATH="${DEPLOY_REPO_PATH:-/opt/skillra_hse_pda}"

usage() {
  cat <<'USAGE'
Usage: scripts/ops_health.sh --profile local|staging|prod [--host HOST]

Checks container and HTTP readiness for local, staging, or production contours.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="$2"
      shift
      ;;
    --host)
      HOST="$2"
      shift
      ;;
    --user)
      USER_NAME="$2"
      shift
      ;;
    --repo-path)
      REPO_PATH="$2"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "[ops-health] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

check_url() {
  local url="$1"
  local label="$2"
  echo "[ops-health] ${label}: ${url}"
  curl -fsS -m 8 "${url}" >/dev/null
}

if [[ "${PROFILE}" == "local" ]]; then
  ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
  COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/infra/docker-compose.dev.yml}"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
  check_url "http://localhost:${SKILLRA_API_PORT:-8000}/health" "API liveness"
  check_url "http://localhost:${SKILLRA_API_PORT:-8000}/v1/health" "API readiness"
  check_url "http://localhost:${SKILLRA_WEB_PORT:-5173}" "Web"
  check_url "http://localhost:${MEILISEARCH_PORT:-7700}/health" "MeiliSearch"
  check_url "http://localhost:${MINIO_PORT:-9000}/minio/health/live" "MinIO"
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T postgres pg_isready -U "${POSTGRES_USER:-skillra}" -d "${POSTGRES_DB:-skillra}"
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T redis redis-cli ping
  echo "[ops-health] Local contour is healthy"
  exit 0
fi

if [[ "${PROFILE}" != "prod" && "${PROFILE}" != "staging" ]]; then
  echo "[ops-health] --profile must be local, staging, or prod" >&2
  exit 2
fi
if [[ -z "${HOST}" ]]; then
  echo "[ops-health] --host is required for ${PROFILE}" >&2
  exit 2
fi

REMOTE_ENV_FILE="${OPS_ENV_FILE:-.env.prod}"
REMOTE_PUBLIC_DEFAULT="https://skillra.ru"
REMOTE_COMPOSE_PROJECT="${OPS_COMPOSE_PROJECT:-}"
REMOTE_COMPOSE_OVERRIDE="${OPS_COMPOSE_OVERRIDE_FILE:-}"
REMOTE_DATA_BASE="${OPS_DATA_BASE:-/var/lib/skillra}"
if [[ "${PROFILE}" == "staging" ]]; then
  REMOTE_ENV_FILE="${OPS_ENV_FILE:-.env.staging}"
  REMOTE_PUBLIC_DEFAULT="https://staging.skillra.ru"
  REMOTE_COMPOSE_PROJECT="${OPS_COMPOSE_PROJECT:-skillra-staging}"
  REMOTE_COMPOSE_OVERRIDE="${OPS_COMPOSE_OVERRIDE_FILE:-infra/docker-compose.staging.yml}"
  REMOTE_DATA_BASE="${OPS_DATA_BASE:-/var/lib/skillra-staging}"
fi

REMOTE_COMPOSE_ARGS=(--env-file "${REMOTE_ENV_FILE}" -f infra/docker-compose.prod.yml)
if [[ -n "${REMOTE_COMPOSE_OVERRIDE}" ]]; then
  REMOTE_COMPOSE_ARGS+=(-f "${REMOTE_COMPOSE_OVERRIDE}")
fi
if [[ -n "${REMOTE_COMPOSE_PROJECT}" ]]; then
  REMOTE_COMPOSE_ARGS=(-p "${REMOTE_COMPOSE_PROJECT}" "${REMOTE_COMPOSE_ARGS[@]}")
fi
REMOTE_COMPOSE="SKILLRA_COMPOSE_ENV_FILE=../${REMOTE_ENV_FILE} SKILLRA_DATA_VOLUME_BASE=${REMOTE_DATA_BASE} docker compose ${REMOTE_COMPOSE_ARGS[*]}"

ssh "${USER_NAME}@${HOST}" "cd '${REPO_PATH}' && \
  set -a && . ./${REMOTE_ENV_FILE} && set +a && \
  ${REMOTE_COMPOSE} ps && \
  curl -fsS -m 8 \"\${SKILLRA_PUBLIC_BASE_URL:-${REMOTE_PUBLIC_DEFAULT}}/health\" >/dev/null && \
  python3 scripts/check_health_contour.py \
    --url \"\${SKILLRA_PUBLIC_BASE_URL:-${REMOTE_PUBLIC_DEFAULT}}/v1/health\" \
    --expected-runtime-env \"\${SKILLRA_RUNTIME_ENV:-${PROFILE}}\" \
    --expected-public-base-url \"\${SKILLRA_PUBLIC_BASE_URL:-${REMOTE_PUBLIC_DEFAULT}}\" && \
  ${REMOTE_COMPOSE} exec -T postgres pg_isready -U \"\${POSTGRES_USER:-skillra}\" -d \"\${POSTGRES_DB:-skillra}\" && \
  ${REMOTE_COMPOSE} exec -T redis redis-cli ping"

echo "[ops-health] ${PROFILE} contour is healthy"
