#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DEPLOY_PROFILE="${DEPLOY_PROFILE:-prod}"
HOST="${DEPLOY_HOST:-93.189.231.4}"
USER_NAME="${DEPLOY_USER:-root}"
REPO_PATH="${DEPLOY_REPO_PATH:-}"
REF="${DEPLOY_REF:-main}"
SOURCE_MODE="${DEPLOY_SOURCE:-rsync}"
ENV_FILE="${DEPLOY_ENV_FILE:-}"
CREDENTIALS_FILE="${DEPLOY_CREDENTIALS_FILE:-}"
REMOTE_ENV_FILE="${DEPLOY_REMOTE_ENV_FILE:-.env.prod}"
COMPOSE_PROJECT="${DEPLOY_COMPOSE_PROJECT:-}"
COMPOSE_OVERRIDE_FILE="${DEPLOY_COMPOSE_OVERRIDE_FILE:-}"
DRY_RUN=0
SMOKE_ONLY=0
REFRESH_DATA=0
RUN_CJM=1
SYNC_DATA="${DEPLOY_SYNC_PROCESSED:-0}"
REMOTE_DATA_OWNER="${DEPLOY_DATA_OWNER:-10001:10001}"
REMOTE_DATA_BASE="${DEPLOY_DATA_BASE:-/var/lib/skillra}"
BOOTSTRAP_FROM_PROD_PROCESSED=0

usage() {
  cat <<'USAGE'
Usage: scripts/deploy_prod.sh [options]

One-command production deploy wrapper for the Skillra VPS contour.

Options:
  --profile PROFILE   Deployment profile: prod or staging. Default: prod
  --host HOST          Target host. Default: 93.189.231.4
  --user USER          SSH user. Default: root
  --repo-path PATH     Repo path on host. Default: /opt/skillra_hse_pda for prod,
                       /opt/skillra_hse_pda_staging for staging
  --ref REF            Git ref to deploy. Default: main
  --source MODE        Code source: rsync or git. Default: rsync
  --env-file FILE      Local env file for validation/upload. Default: .env.prod for prod,
                       .env.staging for staging
  --remote-env-file FILE
                      Remote env file name under --repo-path. Default: .env.prod
  --credentials-file FILE
                      Optional local-only credentials for smoke Basic Auth.
                      Default: .env.prod.credentials or .env.staging.credentials.
  --compose-project NAME
                      Optional docker compose project name.
  --compose-override FILE
                      Optional compose override file, relative to repo root.
  --data-base PATH     Remote data base directory. Default: /var/lib/skillra.
  --dry-run            Print and validate the plan without changing the host.
  --smoke-only         Run profile health/smoke without git/build/up.
  --refresh-data       Run profile data refresh after deploy.
  --sync-data          In rsync mode, sync local data/processed to VPS. Disabled by default;
                       use only for one-time bootstrap, not normal prod deploys.
  --no-sync-data       In rsync mode, do not sync local data/processed to VPS.
  --bootstrap-from-prod-processed
                      Staging only: copy /var/lib/skillra/processed to the staging
                      data base, sync processed artifacts to staging MinIO and
                      publish/reload the mounted active dataset before smoke.
  --no-cjm             Skip CJM smoke after API smoke.
  -h, --help           Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift ;;
    --profile) DEPLOY_PROFILE="$2"; shift ;;
    --user) USER_NAME="$2"; shift ;;
    --repo-path) REPO_PATH="$2"; shift ;;
    --ref) REF="$2"; shift ;;
    --source) SOURCE_MODE="$2"; shift ;;
    --env-file) ENV_FILE="$2"; shift ;;
    --remote-env-file) REMOTE_ENV_FILE="$2"; shift ;;
    --credentials-file) CREDENTIALS_FILE="$2"; shift ;;
    --compose-project) COMPOSE_PROJECT="$2"; shift ;;
    --compose-override) COMPOSE_OVERRIDE_FILE="$2"; shift ;;
    --data-base) REMOTE_DATA_BASE="$2"; shift ;;
    --dry-run) DRY_RUN=1 ;;
    --smoke-only) SMOKE_ONLY=1 ;;
    --refresh-data) REFRESH_DATA=1 ;;
    --sync-data) SYNC_DATA=1 ;;
    --no-sync-data) SYNC_DATA=0 ;;
    --bootstrap-from-prod-processed) BOOTSTRAP_FROM_PROD_PROCESSED=1 ;;
    --no-cjm) RUN_CJM=0 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "[deploy-prod] Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

PYTHON_BIN="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi
if [[ "${SOURCE_MODE}" != "rsync" && "${SOURCE_MODE}" != "git" ]]; then
  echo "[deploy-prod] --source must be 'rsync' or 'git', got '${SOURCE_MODE}'" >&2
  exit 2
fi
if [[ "${DEPLOY_PROFILE}" != "prod" && "${DEPLOY_PROFILE}" != "staging" ]]; then
  echo "[deploy-prod] --profile must be 'prod' or 'staging', got '${DEPLOY_PROFILE}'" >&2
  exit 2
fi
if [[ "${DEPLOY_PROFILE}" == "staging" ]]; then
  REPO_PATH="${REPO_PATH:-/opt/skillra_hse_pda_staging}"
  ENV_FILE="${ENV_FILE:-${STAGING_ENV_FILE:-${REPO_ROOT}/.env.staging}}"
  CREDENTIALS_FILE="${CREDENTIALS_FILE:-${STAGING_CREDENTIALS_FILE:-${REPO_ROOT}/.env.staging.credentials}}"
  REMOTE_ENV_FILE="${DEPLOY_REMOTE_ENV_FILE:-.env.staging}"
  REMOTE_DATA_BASE="${DEPLOY_DATA_BASE:-/var/lib/skillra-staging}"
  COMPOSE_PROJECT="${DEPLOY_COMPOSE_PROJECT:-skillra-staging}"
  COMPOSE_OVERRIDE_FILE="${DEPLOY_COMPOSE_OVERRIDE_FILE:-infra/docker-compose.staging.yml}"
  if [[ "${REMOTE_ENV_FILE}" == ".env.prod" ]]; then
    echo "[deploy-prod] staging deploy must not use .env.prod as remote env file" >&2
    exit 2
  fi
  if [[ "${REPO_PATH%/}" == "/opt/skillra_hse_pda" ]]; then
    echo "[deploy-prod] staging deploy must use a repo path isolated from production" >&2
    exit 2
  fi
  if [[ "${REMOTE_DATA_BASE%/}" == "/var/lib/skillra" ]]; then
    echo "[deploy-prod] staging deploy must use a data base isolated from production" >&2
    exit 2
  fi
  if [[ -z "${COMPOSE_PROJECT}" || "${COMPOSE_PROJECT}" == "skillra" ]]; then
    echo "[deploy-prod] staging deploy must use a non-production compose project" >&2
    exit 2
  fi
elif [[ "${BOOTSTRAP_FROM_PROD_PROCESSED}" -eq 1 ]]; then
  echo "[deploy-prod] --bootstrap-from-prod-processed is staging-only" >&2
  exit 2
else
  REPO_PATH="${REPO_PATH:-/opt/skillra_hse_pda}"
  ENV_FILE="${ENV_FILE:-${PROD_ENV_FILE:-${REPO_ROOT}/.env.prod}}"
  CREDENTIALS_FILE="${CREDENTIALS_FILE:-${PROD_CREDENTIALS_FILE:-${REPO_ROOT}/.env.prod.credentials}}"
fi
if [[ "${ENV_FILE}" != /* ]]; then
  ENV_FILE="${REPO_ROOT}/${ENV_FILE}"
fi
if [[ "${CREDENTIALS_FILE}" != /* ]]; then
  CREDENTIALS_FILE="${REPO_ROOT}/${CREDENTIALS_FILE}"
fi
LOCAL_COMPOSE_ENV_FILE="${ENV_FILE}"
if [[ "${ENV_FILE}" == "${REPO_ROOT}/"* ]]; then
  LOCAL_COMPOSE_ENV_FILE="../${ENV_FILE#"${REPO_ROOT}/"}"
fi

echo "[deploy-prod] Local preflight for ${DEPLOY_PROFILE} ${USER_NAME}@${HOST}:${REPO_PATH} source=${SOURCE_MODE} ref=${REF}"
"${PYTHON_BIN}" "${REPO_ROOT}/scripts/env_doctor.py" --profile "${DEPLOY_PROFILE}" --env-file "${ENV_FILE}"
LOCAL_COMPOSE_ARGS=(--env-file "${ENV_FILE}" -f "${REPO_ROOT}/infra/docker-compose.prod.yml")
if [[ -n "${COMPOSE_OVERRIDE_FILE}" ]]; then
  LOCAL_COMPOSE_ARGS+=(-f "${REPO_ROOT}/${COMPOSE_OVERRIDE_FILE}")
fi
if [[ -n "${COMPOSE_PROJECT}" ]]; then
  LOCAL_COMPOSE_ARGS=(-p "${COMPOSE_PROJECT}" "${LOCAL_COMPOSE_ARGS[@]}")
fi
SKILLRA_COMPOSE_ENV_FILE="${LOCAL_COMPOSE_ENV_FILE}" docker compose "${LOCAL_COMPOSE_ARGS[@]}" --profile monitoring --profile ops config -q

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[deploy-prod] Dry run only. Planned remote flow:"
  if [[ "${SOURCE_MODE}" == "git" ]]; then
    echo "  cd ${REPO_PATH}"
    echo "  git fetch --all --prune && git checkout ${REF} && git pull --ff-only"
  else
    echo "  rsync current working tree to ${USER_NAME}@${HOST}:${REPO_PATH}"
      echo "  upload ${ENV_FILE} to ${REPO_PATH}/${REMOTE_ENV_FILE}"
      if [[ "${SYNC_DATA}" -eq 1 ]]; then
        echo "  rsync data/processed to ${REMOTE_DATA_BASE}/processed"
      else
        echo "  skip data/processed sync; ${DEPLOY_PROFILE} pipeline owns ${REMOTE_DATA_BASE}/processed"
      fi
    fi
  echo "  docker compose config/build/migrate/up --profile monitoring"
  if [[ "${BOOTSTRAP_FROM_PROD_PROCESSED}" -eq 1 ]]; then
    echo "  bootstrap staging processed data from /var/lib/skillra/processed"
    echo "  sync staging processed artifacts to staging MinIO"
    echo "  publish/reload active dataset before smoke"
  fi
  echo "  health + strict smoke + CJM smoke"
  exit 0
fi

REMOTE_TARGET="${USER_NAME}@${HOST}"
COMPOSE_REMOTE_ARGS=(--env-file "${REMOTE_ENV_FILE}" -f infra/docker-compose.prod.yml)
if [[ -n "${COMPOSE_OVERRIDE_FILE}" ]]; then
  COMPOSE_REMOTE_ARGS+=(-f "${COMPOSE_OVERRIDE_FILE}")
fi
if [[ -n "${COMPOSE_PROJECT}" ]]; then
  COMPOSE_REMOTE_ARGS=(-p "${COMPOSE_PROJECT}" "${COMPOSE_REMOTE_ARGS[@]}")
fi
COMPOSE_REMOTE="SKILLRA_COMPOSE_ENV_FILE=../${REMOTE_ENV_FILE} SKILLRA_DATA_VOLUME_BASE=${REMOTE_DATA_BASE} docker compose ${COMPOSE_REMOTE_ARGS[*]}"

prepare_remote_data_dirs() {
  ssh "${REMOTE_TARGET}" "mkdir -p '${REPO_PATH}' '${REMOTE_DATA_BASE}/processed' '${REMOTE_DATA_BASE}/raw/hh' '${REMOTE_DATA_BASE}/metrics' && chown -R '${REMOTE_DATA_OWNER}' '${REMOTE_DATA_BASE}/processed' '${REMOTE_DATA_BASE}/raw/hh' '${REMOTE_DATA_BASE}/metrics' && chmod -R u+rwX,g+rwX '${REMOTE_DATA_BASE}/processed' '${REMOTE_DATA_BASE}/raw/hh' '${REMOTE_DATA_BASE}/metrics'"
}

sync_tree() {
  echo "[deploy-prod] Syncing working tree to ${REMOTE_TARGET}:${REPO_PATH}"
  prepare_remote_data_dirs
  rsync -az --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '.cache/' \
    --exclude '.mypy_cache/' \
    --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' \
    --exclude '.pip-tools-cache/' \
    --exclude '__pycache__/' \
    --exclude 'node_modules/' \
    --exclude 'apps/skillra_web/node_modules/' \
    --exclude 'apps/skillra_web/dist/' \
    --exclude '.env' \
    --exclude '.env.prod' \
    --exclude '.env.staging' \
    --exclude '.env.prod.credentials' \
    --exclude '.env.staging.credentials' \
    --exclude 'data/raw/hh/' \
    --exclude 'data/processed/' \
    --exclude 'reports/smoke/*.json' \
    "${REPO_ROOT}/" "${REMOTE_TARGET}:${REPO_PATH}/"
  rsync -az "${ENV_FILE}" "${REMOTE_TARGET}:${REPO_PATH}/${REMOTE_ENV_FILE}"
  ssh "${REMOTE_TARGET}" "chmod 600 '${REPO_PATH}/${REMOTE_ENV_FILE}'"
  if [[ "${SYNC_DATA}" -eq 1 && -d "${REPO_ROOT}/data/processed" ]]; then
    echo "[deploy-prod] Syncing processed data to ${REMOTE_TARGET}:${REMOTE_DATA_BASE}/processed"
    rsync -az --delete "${REPO_ROOT}/data/processed/" "${REMOTE_TARGET}:${REMOTE_DATA_BASE}/processed/"
    prepare_remote_data_dirs
  fi
}

if [[ "${SMOKE_ONLY}" -eq 0 ]]; then
  if [[ "${SOURCE_MODE}" == "git" ]]; then
    echo "[deploy-prod] Updating git checkout on ${REMOTE_TARGET}"
    ssh "${REMOTE_TARGET}" "cd '${REPO_PATH}' && git fetch --all --prune && git checkout '${REF}' && git pull --ff-only"
  else
    sync_tree
  fi

  echo "[deploy-prod] Applying compose on ${REMOTE_TARGET}"
  ssh "${REMOTE_TARGET}" "cd '${REPO_PATH}' && \
    ${COMPOSE_REMOTE} --profile monitoring --profile ops config -q && \
    ${COMPOSE_REMOTE} --profile monitoring --profile ops build && \
    ${COMPOSE_REMOTE} run --rm migrator && \
    ${COMPOSE_REMOTE} --profile monitoring up -d --remove-orphans && \
    ${COMPOSE_REMOTE} --profile monitoring up -d --force-recreate --no-deps caddy"

  if [[ "${BOOTSTRAP_FROM_PROD_PROCESSED}" -eq 1 ]]; then
    echo "[deploy-prod] Bootstrapping staging dataset from production processed artifacts"
    ssh "${REMOTE_TARGET}" "set -euo pipefail; \
      mkdir -p '${REMOTE_DATA_BASE}/processed' '${REMOTE_DATA_BASE}/metrics'; \
      rsync -a --delete /var/lib/skillra/processed/ '${REMOTE_DATA_BASE}/processed/'; \
      chown -R '${REMOTE_DATA_OWNER}' '${REMOTE_DATA_BASE}/processed' '${REMOTE_DATA_BASE}/metrics'"
    ssh "${REMOTE_TARGET}" "cd '${REPO_PATH}' && \
      set -a && . './${REMOTE_ENV_FILE}' && set +a && \
      ${COMPOSE_REMOTE} --profile ops run --rm --no-deps pipeline_runner \
        python scripts/s3_sync_processed.py --storage-dir /workspace/data/processed --overwrite --publish-active-pointer && \
      ${COMPOSE_REMOTE} --profile ops run --rm --no-deps pipeline_runner \
        python scripts/bootstrap_active_dataset.py \
          --base-url http://skillra-api:8000 \
          --token \"\${SKILLRA_API_TOKEN}\" \
          --admin-token \"\${SKILLRA_ADMIN_TOKEN}\" \
          --data-dir /workspace/data/processed"
  fi

  if [[ "${REFRESH_DATA}" -eq 1 ]]; then
    echo "[deploy-prod] Running ${DEPLOY_PROFILE} data refresh"
    ssh "${REMOTE_TARGET}" "cd '${REPO_PATH}' && ${COMPOSE_REMOTE} --profile ops run -e SKILLRA_REFRESH_HH=1 -e SKILLRA_S3_SYNC=1 -e SKILLRA_REQUIRE_RAW_S3_COMMIT=1 --rm pipeline_runner"
  fi
fi

echo "[deploy-prod] Waiting for ${DEPLOY_PROFILE} health"
bash "${REPO_ROOT}/scripts/ops_health.sh" --profile "${DEPLOY_PROFILE}" --host "${HOST}" --user "${USER_NAME}" --repo-path "${REPO_PATH}"

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
if [[ -f "${CREDENTIALS_FILE}" ]]; then
  # shellcheck disable=SC1090
  . "${CREDENTIALS_FILE}"
fi
set +a
DEFAULT_PUBLIC_URL="https://skillra.ru"
if [[ "${DEPLOY_PROFILE}" == "staging" ]]; then
  DEFAULT_PUBLIC_URL="https://staging.skillra.ru"
fi
SMOKE_BASE_URL="${SKILLRA_PUBLIC_BASE_URL:-${DEFAULT_PUBLIC_URL}}"

echo "[deploy-prod] Running strict ${DEPLOY_PROFILE} API smoke"
PYTHONPATH="${REPO_ROOT}/src:${REPO_ROOT}/apps/skillra_api/src:${REPO_ROOT}/apps/telegram_bot:${REPO_ROOT}/apps/digest_worker${PYTHONPATH:+:${PYTHONPATH}}" \
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/smoke_skillra_platform.py" \
    --base-url "${SMOKE_BASE_URL}" \
    --token "${SKILLRA_API_TOKEN}" \
    --admin-token "${SKILLRA_ADMIN_TOKEN}" \
    --sprint12-checks strict \
    --search-index-checks strict \
    --storage-checks strict \
    --expected-runtime-env "${DEPLOY_PROFILE}" \
    --expected-public-base-url "${SMOKE_BASE_URL}"

if [[ "${RUN_CJM}" -eq 1 ]]; then
  echo "[deploy-prod] Running ${DEPLOY_PROFILE} CJM smoke"
  PYTHONPATH="${REPO_ROOT}/src:${REPO_ROOT}/apps/skillra_api/src:${REPO_ROOT}/apps/telegram_bot:${REPO_ROOT}/apps/digest_worker${PYTHONPATH:+:${PYTHONPATH}}" \
    "${PYTHON_BIN}" "${REPO_ROOT}/scripts/smoke_cjm_flow.py" \
      --base-url "${SMOKE_BASE_URL}" \
      --token "${SKILLRA_API_TOKEN}" \
      --admin-token "${SKILLRA_ADMIN_TOKEN}" \
      --strict --prod-safe
fi

echo "[deploy-prod] ${DEPLOY_PROFILE} deploy completed"
