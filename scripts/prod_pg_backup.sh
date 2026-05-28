#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${SKILLRA_REPO_DIR:-/opt/skillra_hse_pda}"
RETENTION_DAYS="${PG_BACKUP_RETENTION_DAYS:-7}"

cd "$REPO_DIR"

exec docker compose \
  --env-file .env.prod \
  -f infra/docker-compose.prod.yml \
  --profile ops \
  run \
  --rm \
  --no-deps \
  pipeline_runner \
  python scripts/pg_backup_to_s3.py \
  --pg-host postgres \
  --pg-port 5432 \
  --retention-days "$RETENTION_DAYS" \
  --metrics-file /workspace/data/metrics/skillra_pg_backup.prom
