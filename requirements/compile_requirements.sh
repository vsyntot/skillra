#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_DIR="${ROOT_DIR}/requirements"
LOCK_DIR="${REQ_DIR}/lock"
API_DIR="${ROOT_DIR}/apps/skillra_api"
BOT_DIR="${ROOT_DIR}/apps/telegram_bot"

mkdir -p "${LOCK_DIR}"

echo "Compiling base requirements to requirements/lock/base.lock.txt..."
pip-compile --output-file "${LOCK_DIR}/base.lock.txt" "${REQ_DIR}/base.txt"

echo "Compiling dev requirements to requirements/lock/dev.lock.txt..."
pip-compile --output-file "${LOCK_DIR}/dev.lock.txt" "${REQ_DIR}/dev.txt"

echo "Compiling Skillra API CI requirements to requirements/lock/skillra_api_ci.lock.txt..."
pip-compile --output-file "${LOCK_DIR}/skillra_api_ci.lock.txt" "${API_DIR}/requirements-ci.txt"

echo "Compiling Skillra API production requirements to requirements/lock/skillra_api_prod.lock.txt..."
pip-compile --output-file "${LOCK_DIR}/skillra_api_prod.lock.txt" "${API_DIR}/requirements-prod.txt"

echo "Compiling Telegram Bot requirements to requirements/lock/telegram_bot.lock.txt..."
pip-compile --output-file "${LOCK_DIR}/telegram_bot.lock.txt" "${BOT_DIR}/requirements.txt"

echo "Requirements compilation complete."
