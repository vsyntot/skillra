#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

REBUILD=1
RUN_SMOKE=1
RUN_CJM=1
EXTRA_ARGS=()

usage() {
  cat <<'USAGE'
Usage: scripts/deploy_local.sh [options]

Applies local changes to the local Docker contour and verifies the product path.

Options:
  --no-build      Do not rebuild Docker images.
  --no-smoke      Skip strict API/search/storage smoke.
  --no-cjm        Skip CJM e2e smoke.
  --with-bot      Start Telegram bot too.
  --with-digest   Start digest worker too.
  -h, --help      Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build) REBUILD=0 ;;
    --no-smoke) RUN_SMOKE=0 ;;
    --no-cjm) RUN_CJM=0 ;;
    --with-bot | --with-digest)
      EXTRA_ARGS+=("$1")
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "[deploy-local] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

LOCAL_UP_ARGS=()
if [[ "${REBUILD}" -eq 1 ]]; then
  LOCAL_UP_ARGS+=(--rebuild)
fi
if [[ "${RUN_SMOKE}" -eq 1 ]]; then
  LOCAL_UP_ARGS+=(--smoke)
fi
if [[ "${#EXTRA_ARGS[@]}" -gt 0 ]]; then
  LOCAL_UP_ARGS+=("${EXTRA_ARGS[@]}")
fi

bash "${REPO_ROOT}/scripts/local_up.sh" "${LOCAL_UP_ARGS[@]}"

if [[ "${RUN_CJM}" -eq 1 ]]; then
  echo "[deploy-local] Running CJM e2e smoke"
  set -a
  # shellcheck disable=SC1091
  source "${ENV_FILE:-${REPO_ROOT}/.env}"
  set +a
  PYTHON_BIN="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
  if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="python3"
  fi
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/smoke_cjm_flow.py" \
    --base-url "http://localhost:${SKILLRA_API_PORT:-8000}" \
    --token "${SKILLRA_API_TOKEN}" \
    --admin-token "${SKILLRA_ADMIN_TOKEN}" \
    --strict
fi

echo "[deploy-local] Local deploy completed"
