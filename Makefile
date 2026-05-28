.PHONY: test pipeline api bot compose-up compose-down compose-logs compose-up-digest compose-down-digest seed-search minio-init minio-lifecycle-render minio-lifecycle-render-prod minio-lifecycle-check minio-lifecycle-check-prod minio-scope-smoke-local minio-scope-smoke-prod trend-readiness-report trend-readiness-report-prod rollback-eligibility-report-prod external-readiness-report pipeline-refresh data-refresh data-refresh-local data-smoke-local data-product-smoke-local data-restore-local-dry-run data-restore-local db-backup-local prod-db-backup prod-db-restore-drill alert-smoke-local alert-smoke-prod monitoring-check readiness-smoke readiness-smoke-staging web-api-contract-check release-candidate-gate secrets-tools-check secrets-bootstrap-prod secrets-set-prod secrets-rotate-prod secrets-render-prod secrets-check-prod secrets-bootstrap-staging secrets-render-staging secrets-check-staging lint format smoke-api smoke-api-staging compose-smoke api-tests bot-tests all-tests ci prod-up prod-down prod-logs prod-up-full prod-down-full prod-logs-full prod-migrate prod-pipeline-refresh prod-data-refresh data-refresh-prod data-smoke-prod data-product-smoke-prod data-product-smoke-staging compose-migrate bootstrap-ci compose-validate env-render env-render-check env-sync-local env-sync-prod env-sync-staging env-minio-roles-prod env-check-local env-check-prod env-check-staging local-up local-smoke local-down deploy-local deploy-prod deploy-prod-dry-run deploy-prod-smoke ensure-staging-deploy-target deploy-staging deploy-staging-dry-run deploy-staging-smoke health-local health-prod health-staging cjm-smoke-local cjm-smoke-prod cjm-smoke-staging telegram-smoke-staging

ENV_FILE ?= .env
COMPOSE_FILE := infra/docker-compose.dev.yml
PROD_ENV_FILE ?= .env.prod
PROD_COMPOSE_FILE := infra/docker-compose.prod.yml
PROD_SECRETS_FILE ?= secrets/prod.sops.yaml
STAGING_ENV_FILE ?= .env.staging
STAGING_COMPOSE_FILE := infra/docker-compose.prod.yml
STAGING_COMPOSE_OVERRIDE_FILE := infra/docker-compose.staging.yml
STAGING_SECRETS_FILE ?= secrets/staging.sops.yaml
TEST_PYTHONPATH := $(CURDIR)/src:$(CURDIR)/apps/skillra_api/src:$(CURDIR)/apps/telegram_bot:$(CURDIR)/apps/digest_worker
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; elif command -v python3 >/dev/null 2>&1; then echo python3; else echo python; fi)
PYTEST ?= $(shell if [ -x .venv/bin/pytest ]; then echo .venv/bin/pytest; else echo pytest; fi)
RUFF ?= $(shell if [ -x .venv/bin/ruff ]; then echo .venv/bin/ruff; else echo ruff; fi)
MYPY ?= $(shell if [ -x .venv/bin/mypy ]; then echo .venv/bin/mypy; else echo mypy; fi)
UVICORN ?= $(shell if [ -x .venv/bin/uvicorn ]; then echo .venv/bin/uvicorn; else echo uvicorn; fi)
DEPLOY_HOST ?= 93.189.231.4
DEPLOY_USER ?= root
DEPLOY_REPO_PATH ?= /opt/skillra_hse_pda
DEPLOY_REF ?= main
DEPLOY_SOURCE ?= rsync
STAGING_DEPLOY_HOST ?=
STAGING_DEPLOY_USER ?= root
STAGING_DEPLOY_REPO_PATH ?= /opt/skillra_hse_pda_staging
STAGING_DEPLOY_REF ?= $(DEPLOY_REF)
STAGING_DEPLOY_SOURCE ?= $(DEPLOY_SOURCE)
STAGING_COMPOSE_PROJECT ?= skillra-staging
STAGING_DATA_BASE ?= /var/lib/skillra-staging
STAGING_COLOCATE_ON_PROD ?= 0
STAGING_BOOTSTRAP_FROM_PROD_PROCESSED ?= 0

# Run unit tests for the learning layer
test:
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTEST) -q

# Run static analysis
lint:
	$(RUFF) check .
	$(RUFF) format --check .

# Apply code formatting (uses Ruff formatter)
format:
	$(RUFF) format .

env-render:
	$(PYTHON) scripts/env_render.py --profile local --output .env.example
	$(PYTHON) scripts/env_render.py --profile prod --output .env.prod.example
	$(PYTHON) scripts/env_render.py --profile staging --output .env.staging.example

env-render-check:
	$(PYTHON) scripts/env_render.py --profile local --output .env.example --check
	$(PYTHON) scripts/env_render.py --profile prod --output .env.prod.example --check
	$(PYTHON) scripts/env_render.py --profile staging --output .env.staging.example --check

env-sync-local:
	$(PYTHON) scripts/env_render.py --profile local --merge-env-file $(ENV_FILE) --output $(ENV_FILE)

env-sync-prod:
	$(PYTHON) scripts/env_render.py --profile prod --merge-env-file $(PROD_ENV_FILE) --output $(PROD_ENV_FILE)

env-sync-staging:
	$(PYTHON) scripts/env_render.py --profile staging --merge-env-file $(STAGING_ENV_FILE) --output $(STAGING_ENV_FILE)

env-minio-roles-prod:
	$(PYTHON) scripts/env_minio_roles.py --env-file $(PROD_ENV_FILE) --write

env-check-local:
	$(PYTHON) scripts/env_doctor.py --profile local --env-file $(ENV_FILE)

env-check-prod:
	$(PYTHON) scripts/env_doctor.py --profile prod --env-file $(PROD_ENV_FILE)

env-check-staging:
	$(PYTHON) scripts/env_doctor.py --profile staging --env-file $(STAGING_ENV_FILE)

secrets-tools-check:
	$(PYTHON) scripts/secrets_tools_check.py

secrets-bootstrap-prod:
	$(PYTHON) scripts/secrets_bootstrap.py --profile prod --env-file $(PROD_ENV_FILE) --output $(PROD_SECRETS_FILE)

secrets-set-prod:
	@test -n "$$SECRET_KEY" || (echo "SECRET_KEY is required, for example SECRET_KEY=TELEGRAM_BOT_TOKEN" >&2; exit 2)
	$(PYTHON) scripts/secrets_set.py --secrets-file $(PROD_SECRETS_FILE) --key "$$SECRET_KEY"

secrets-rotate-prod:
	@test -n "$$SECRET_KEY" || (echo "SECRET_KEY is required, for example SECRET_KEY=TELEGRAM_BOT_TOKEN" >&2; exit 2)
	$(PYTHON) scripts/secrets_set.py --secrets-file $(PROD_SECRETS_FILE) --key "$$SECRET_KEY" --require-change
	$(PYTHON) scripts/secrets_render.py --profile prod --secrets-file $(PROD_SECRETS_FILE) --output $(PROD_ENV_FILE) --dry-run --validate

secrets-render-prod:
	$(PYTHON) scripts/secrets_render.py --profile prod --secrets-file $(PROD_SECRETS_FILE) --output $(PROD_ENV_FILE) --validate

secrets-check-prod:
	$(PYTHON) scripts/secrets_render.py --profile prod --secrets-file $(PROD_SECRETS_FILE) --output $(PROD_ENV_FILE) --dry-run --validate

secrets-bootstrap-staging:
	$(PYTHON) scripts/secrets_bootstrap.py --profile staging --env-file $(STAGING_ENV_FILE) --output $(STAGING_SECRETS_FILE)

secrets-render-staging:
	$(PYTHON) scripts/secrets_render.py --profile staging --secrets-file $(STAGING_SECRETS_FILE) --output $(STAGING_ENV_FILE) --validate

secrets-check-staging:
	$(PYTHON) scripts/secrets_render.py --profile staging --secrets-file $(STAGING_SECRETS_FILE) --output $(STAGING_ENV_FILE) --dry-run --validate

# Bootstrap CI dependencies in a clean environment
bootstrap-ci:
	$(PYTHON) -m pip install --upgrade "pip<25"
	$(PYTHON) -m pip install -r requirements/lock/base.lock.txt
	$(PYTHON) -m pip install -r requirements/lock/dev.lock.txt
	$(PYTHON) -m pip install -r requirements/lock/skillra_api_ci.lock.txt
	$(PYTHON) -m pip install -r requirements/lock/telegram_bot.lock.txt
	$(PYTHON) -m pip install -e .
	$(PYTHON) -m pip install -e apps/skillra_api
	$(PYTHON) -m pip install -e apps/telegram_bot
	$(PYTHON) -m pip install -e apps/digest_worker

# Run the data pipeline to regenerate processed datasets
pipeline:
	$(PYTHON) scripts/run_pipeline.py

# Start the Skillra API (development)
api:
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(UVICORN) skillra_api.main:app --host $${SKILLRA_API_HOST:-0.0.0.0} --port $${SKILLRA_API_PORT:-8000} --reload

# Start the Telegram bot (development)
bot:
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTHON) -m telegram_bot.main

# Bring up local services via docker-compose
compose-up:
	mkdir -p data/processed
	mkdir -p data/raw/hh
	mkdir -p data/metrics
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) up -d

# Tail logs from docker-compose services
# Safe manual check: проверить make -n compose-logs
compose-logs:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) logs -f

# Tear down local services
compose-down:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) down

compose-up-digest:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile digest up -d digest-worker

compose-down-digest:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile digest stop digest-worker

compose-migrate:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) run --rm migrator

prod-up:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) up -d

prod-up-full:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile storage --profile monitoring up -d

prod-logs:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) logs -f

prod-logs-full:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile storage --profile monitoring logs -f

prod-down:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) down

prod-down-full:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile storage --profile monitoring down

prod-migrate:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) run --rm migrator

prod-pipeline-refresh:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run -e SKILLRA_USE_RAW_HH_LATEST=1 -e SKILLRA_S3_SYNC=1 -e SKILLRA_REQUIRE_RAW_S3_COMMIT=1 --rm pipeline_runner

# Daily HH refresh (dev compose): snapshot + delta + pipeline + reload hook
data-refresh:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run -e SKILLRA_REFRESH_HH=1 --rm pipeline_runner

data-refresh-local:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run -e SKILLRA_REFRESH_HH=1 -e SKILLRA_S3_SYNC=1 -e SKILLRA_REQUIRE_RAW_S3_COMMIT=1 --rm pipeline_runner

data-smoke-local:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run --no-deps -e SKILLRA_REQUIRE_RAW_S3_COMMIT=1 --rm pipeline_runner python scripts/raw_hh_gate.py --storage-dir data/raw/hh --require-s3

data-product-smoke-local:
	set -a; . $(ENV_FILE); set +a; API_PORT=$${SKILLRA_API_PORT:-8000}; BASE_URL=$${SKILLRA_SMOKE_API_BASE_URL:-http://localhost:$$API_PORT}; PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTHON) scripts/smoke_data_product_release.py --base-url $$BASE_URL --token $$SKILLRA_API_TOKEN --admin-token $$SKILLRA_ADMIN_TOKEN

# Daily HH refresh (prod compose): snapshot + delta + pipeline + reload hook
prod-data-refresh:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run -e SKILLRA_REFRESH_HH=1 -e SKILLRA_S3_SYNC=1 -e SKILLRA_REQUIRE_RAW_S3_COMMIT=1 --rm pipeline_runner

data-refresh-prod: prod-data-refresh

data-smoke-prod:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run --no-deps -e SKILLRA_REQUIRE_RAW_S3_COMMIT=1 --rm pipeline_runner python scripts/raw_hh_gate.py --storage-dir data/raw/hh --require-s3

data-product-smoke-prod:
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "cd '$(DEPLOY_REPO_PATH)' && set -a; . $(PROD_ENV_FILE); if [ -f .env.prod.credentials ]; then . .env.prod.credentials; fi; set +a; docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/smoke_data_product_release.py --base-url http://prod-skillra-api:8000 --token \"\$$SKILLRA_API_TOKEN\" --admin-token \"\$$SKILLRA_ADMIN_TOKEN\" --expected-runtime-env \"\$${SKILLRA_RUNTIME_ENV:-prod}\" --expected-public-base-url \"\$${SKILLRA_PUBLIC_BASE_URL:-https://skillra.ru}\" --require-processed-s3 --processed-bucket \"\$$S3_BUCKET_PROCESSED\" --report data/metrics/data_product_release.json"

trend-readiness-report:
	$(PYTHON) scripts/trend_readiness_report.py --processed-runs-dir data/processed/runs --output reports/acceptance/trend_readiness_report.local.json --require-public-blocked

trend-readiness-report-prod:
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "cd '$(DEPLOY_REPO_PATH)' && docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/trend_readiness_report.py --processed-runs-dir /workspace/data/processed/runs --output /workspace/data/metrics/trend_readiness_report.json --require-public-blocked"

rollback-eligibility-report-prod:
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "cd '$(DEPLOY_REPO_PATH)' && set -a; . $(PROD_ENV_FILE); if [ -f .env.prod.credentials ]; then . .env.prod.credentials; fi; set +a; docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/rollback_eligibility_report.py --base-url http://prod-skillra-api:8000 --token \"\$$SKILLRA_API_TOKEN\" --admin-token \"\$$SKILLRA_ADMIN_TOKEN\" --output /workspace/data/metrics/rollback_eligibility_report.json --require-active-unchanged"

external-readiness-report:
	$(PYTHON) scripts/external_dependency_readiness.py

data-restore-local-dry-run:
	mkdir -p data/processed data/raw/hh
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/s3_restore.py --raw-hh-latest --raw-storage-dir /workspace/data/raw/hh --dry-run --overwrite
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/s3_restore.py --processed-latest --processed-storage-dir /workspace/data/processed --dry-run --overwrite

data-restore-local:
	@test "$${DATA_RESTORE_CONFIRM:-0}" = "1" || (echo "Refusing local data restore without DATA_RESTORE_CONFIRM=1"; exit 2)
	mkdir -p data/processed data/raw/hh
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/s3_restore.py --raw-hh-latest --raw-storage-dir /workspace/data/raw/hh --overwrite
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/s3_restore.py --processed-latest --processed-storage-dir /workspace/data/processed --overwrite

db-backup-local:
	mkdir -p data/metrics
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/pg_backup_to_s3.py --pg-host postgres --pg-port 5432 --retention-days $${PG_BACKUP_RETENTION_DAYS:-7} --metrics-file /workspace/data/metrics/skillra_pg_backup.prom

prod-db-backup:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/pg_backup_to_s3.py --pg-host postgres --pg-port 5432 --retention-days $${PG_BACKUP_RETENTION_DAYS:-7} --metrics-file /workspace/data/metrics/skillra_pg_backup.prom

prod-db-restore-drill:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/pg_restore_drill.py --pg-host postgres --pg-port 5432 --metrics-file /workspace/data/metrics/skillra_pg_restore_drill.prom

alert-smoke-local:
	$(PYTHON) scripts/smoke_alert_delivery.py --alertmanager-url $${ALERTMANAGER_URL:-http://localhost:9093}

alert-smoke-prod:
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "cd '$(DEPLOY_REPO_PATH)' && docker compose --env-file .env.prod -f infra/docker-compose.prod.yml --profile monitoring exec -T skillra-api python scripts/smoke_alert_delivery.py --alertmanager-url http://alertmanager:9093"

monitoring-check:
	$(PYTHON) scripts/check_monitoring_config.py

readiness-smoke:
	@test -n "$$SKILLRA_READY_URLS" || (echo "SKILLRA_READY_URLS is required, comma-separated direct /v1/ready URLs for API replicas" >&2; exit 2)
	$(PYTHON) scripts/smoke_multi_replica_readiness.py --urls "$$SKILLRA_READY_URLS"

web-api-contract-check:
	cd apps/skillra_web && npm run generate:api:check

release-candidate-gate:
	@test -n "$$RC_ID" || (echo "RC_ID is required, for example RC_ID=rc-2026-05-27-1" >&2; exit 2)
	$(PYTHON) scripts/release_candidate_gate.py --rc-id "$$RC_ID" --ref "$(DEPLOY_REF)"

# Refresh processed data via docker compose (runs pipeline + reload hook)
pipeline-refresh:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) up -d skillra-api
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run -e SKILLRA_USE_RAW_HH_LATEST=1 -e SKILLRA_S3_SYNC=1 -e SKILLRA_REQUIRE_RAW_S3_COMMIT=1 --rm pipeline_runner

# Run smoke test against Skillra API
smoke-api:
	@if [ -z "$$SKILLRA_API_TOKEN" ]; then \
		echo "SKILLRA_API_TOKEN is required to run smoke-api. Please export it and retry."; \
		exit 1; \
	fi; \
	BASE_URL=$${SKILLRA_SMOKE_API_BASE_URL:-http://localhost:8000}; \
	OUTPUT_ARG=$${SMOKE_OUTPUT:+--output $$SMOKE_OUTPUT}; \
	echo "Running API smoke test against $$BASE_URL"; \
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTHON) scripts/smoke_skillra_platform.py --base-url $$BASE_URL --token $$SKILLRA_API_TOKEN $$OUTPUT_ARG

compose-smoke:
	bash scripts/compose_smoke.sh

local-up:
	bash scripts/local_up.sh

local-smoke:
	bash scripts/local_up.sh --smoke

local-down:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) down

deploy-local:
	bash scripts/deploy_local.sh

health-local:
	bash scripts/ops_health.sh --profile local

health-prod:
	bash scripts/ops_health.sh --profile prod --host $(DEPLOY_HOST) --user $(DEPLOY_USER) --repo-path $(DEPLOY_REPO_PATH)

ensure-staging-deploy-target:
	@test -n "$(STAGING_DEPLOY_HOST)" || (echo "STAGING_DEPLOY_HOST is required" >&2; exit 2)
	@if [ "$(STAGING_DEPLOY_HOST)" = "$(DEPLOY_HOST)" ] && [ "$(STAGING_COLOCATE_ON_PROD)" != "1" ]; then \
		echo "STAGING_DEPLOY_HOST equals DEPLOY_HOST; set STAGING_COLOCATE_ON_PROD=1 only for the portless co-located staging topology" >&2; \
		exit 2; \
	fi
	@test "$(STAGING_DEPLOY_REPO_PATH)" != "$(DEPLOY_REPO_PATH)" || (echo "STAGING_DEPLOY_REPO_PATH must not equal DEPLOY_REPO_PATH" >&2; exit 2)
	@test "$(STAGING_DATA_BASE)" != "/var/lib/skillra" || (echo "STAGING_DATA_BASE must not equal production data base" >&2; exit 2)
	@test "$(STAGING_COMPOSE_PROJECT)" != "skillra" || (echo "STAGING_COMPOSE_PROJECT must not be production compose project" >&2; exit 2)

health-staging: ensure-staging-deploy-target
	bash scripts/ops_health.sh --profile staging --host $(STAGING_DEPLOY_HOST) --user $(STAGING_DEPLOY_USER) --repo-path $(STAGING_DEPLOY_REPO_PATH)

deploy-prod:
	bash scripts/deploy_prod.sh --host $(DEPLOY_HOST) --user $(DEPLOY_USER) --repo-path $(DEPLOY_REPO_PATH) --ref $(DEPLOY_REF) --source $(DEPLOY_SOURCE) --env-file $(PROD_ENV_FILE)

deploy-prod-dry-run:
	bash scripts/deploy_prod.sh --host $(DEPLOY_HOST) --user $(DEPLOY_USER) --repo-path $(DEPLOY_REPO_PATH) --ref $(DEPLOY_REF) --source $(DEPLOY_SOURCE) --env-file $(PROD_ENV_FILE) --dry-run

deploy-prod-smoke:
	bash scripts/deploy_prod.sh --host $(DEPLOY_HOST) --user $(DEPLOY_USER) --repo-path $(DEPLOY_REPO_PATH) --ref $(DEPLOY_REF) --source $(DEPLOY_SOURCE) --env-file $(PROD_ENV_FILE) --smoke-only

deploy-staging: ensure-staging-deploy-target
	bash scripts/deploy_prod.sh --profile staging --host $(STAGING_DEPLOY_HOST) --user $(STAGING_DEPLOY_USER) --repo-path $(STAGING_DEPLOY_REPO_PATH) --ref $(STAGING_DEPLOY_REF) --source $(STAGING_DEPLOY_SOURCE) --env-file $(STAGING_ENV_FILE) --remote-env-file .env.staging --compose-project $(STAGING_COMPOSE_PROJECT) --compose-override $(STAGING_COMPOSE_OVERRIDE_FILE) --data-base $(STAGING_DATA_BASE) $(if $(filter 1 true yes,$(STAGING_BOOTSTRAP_FROM_PROD_PROCESSED)),--bootstrap-from-prod-processed,)

deploy-staging-dry-run: ensure-staging-deploy-target
	bash scripts/deploy_prod.sh --profile staging --host $(STAGING_DEPLOY_HOST) --user $(STAGING_DEPLOY_USER) --repo-path $(STAGING_DEPLOY_REPO_PATH) --ref $(STAGING_DEPLOY_REF) --source $(STAGING_DEPLOY_SOURCE) --env-file $(STAGING_ENV_FILE) --remote-env-file .env.staging --compose-project $(STAGING_COMPOSE_PROJECT) --compose-override $(STAGING_COMPOSE_OVERRIDE_FILE) --data-base $(STAGING_DATA_BASE) $(if $(filter 1 true yes,$(STAGING_BOOTSTRAP_FROM_PROD_PROCESSED)),--bootstrap-from-prod-processed,) --dry-run

deploy-staging-smoke: ensure-staging-deploy-target
	bash scripts/deploy_prod.sh --profile staging --host $(STAGING_DEPLOY_HOST) --user $(STAGING_DEPLOY_USER) --repo-path $(STAGING_DEPLOY_REPO_PATH) --ref $(STAGING_DEPLOY_REF) --source $(STAGING_DEPLOY_SOURCE) --env-file $(STAGING_ENV_FILE) --remote-env-file .env.staging --compose-project $(STAGING_COMPOSE_PROJECT) --compose-override $(STAGING_COMPOSE_OVERRIDE_FILE) --data-base $(STAGING_DATA_BASE) --smoke-only

cjm-smoke-local:
	. $(ENV_FILE); API_PORT=$${SKILLRA_API_PORT:-8000}; BASE_URL=$${SKILLRA_SMOKE_API_BASE_URL:-http://localhost:$$API_PORT}; $(PYTHON) scripts/smoke_cjm_flow.py --base-url $$BASE_URL --token $$SKILLRA_API_TOKEN --admin-token $$SKILLRA_ADMIN_TOKEN --strict

cjm-smoke-prod:
	set -a; . $(PROD_ENV_FILE); if [ -f .env.prod.credentials ]; then . .env.prod.credentials; fi; set +a; $(PYTHON) scripts/smoke_cjm_flow.py --base-url $${SKILLRA_PUBLIC_BASE_URL:-https://skillra.ru} --token $$SKILLRA_API_TOKEN --admin-token $$SKILLRA_ADMIN_TOKEN --strict --prod-safe

cjm-smoke-staging:
	set -a; . $(STAGING_ENV_FILE); if [ -f .env.staging.credentials ]; then . .env.staging.credentials; fi; set +a; $(PYTHON) scripts/smoke_cjm_flow.py --base-url $${SKILLRA_PUBLIC_BASE_URL:-https://staging.skillra.ru} --token $$SKILLRA_API_TOKEN --admin-token $$SKILLRA_ADMIN_TOKEN --strict --prod-safe --report $${CJM_SMOKE_REPORT:-reports/acceptance/cjm_smoke_staging.json}

smoke-api-staging:
	set -a; . $(STAGING_ENV_FILE); if [ -f .env.staging.credentials ]; then . .env.staging.credentials; fi; set +a; PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTHON) scripts/smoke_skillra_platform.py --base-url $${SKILLRA_PUBLIC_BASE_URL:-https://staging.skillra.ru} --token $$SKILLRA_API_TOKEN --admin-token $$SKILLRA_ADMIN_TOKEN --sprint12-checks strict --search-index-checks strict --storage-checks strict --expected-runtime-env $${SKILLRA_RUNTIME_ENV:-staging} --expected-public-base-url $${SKILLRA_PUBLIC_BASE_URL:-https://staging.skillra.ru}

telegram-smoke-staging:
	set -a; . $(STAGING_ENV_FILE); set +a; WEBHOOK_ARG=""; if [ "$${BOT_MODE:-polling}" = "webhook" ]; then WEBHOOK_ARG="--webhook-url $${TELEGRAM_WEBHOOK_URL:-https://tg.staging.skillra.ru/webhook}"; fi; $(PYTHON) scripts/smoke_telegram_bot.py --expected-contour staging --expected-username $${TELEGRAM_BOT_USERNAME:-skillra_staging_bot} --forbid-username $${TELEGRAM_PROD_BOT_USERNAME:-skillra_bot} $$WEBHOOK_ARG --public-health-url $${TELEGRAM_PUBLIC_HEALTH_URL:-https://tg.staging.skillra.ru/health} --report $${TELEGRAM_SMOKE_REPORT:-reports/acceptance/telegram_smoke_staging.json}

readiness-smoke-staging:
	@test -n "$$STAGING_READY_URLS" || (echo "STAGING_READY_URLS is required, comma-separated direct /v1/ready URLs for staging API replicas" >&2; exit 2)
	$(PYTHON) scripts/smoke_multi_replica_readiness.py --urls "$$STAGING_READY_URLS"

data-product-smoke-staging: ensure-staging-deploy-target
	ssh $(STAGING_DEPLOY_USER)@$(STAGING_DEPLOY_HOST) "cd '$(STAGING_DEPLOY_REPO_PATH)' && set -a; . $(STAGING_ENV_FILE); if [ -f .env.staging.credentials ]; then . .env.staging.credentials; fi; set +a; SKILLRA_COMPOSE_ENV_FILE=../$(STAGING_ENV_FILE) SKILLRA_DATA_VOLUME_BASE=$(STAGING_DATA_BASE) docker compose -p $(STAGING_COMPOSE_PROJECT) --env-file $(STAGING_ENV_FILE) -f $(STAGING_COMPOSE_FILE) -f $(STAGING_COMPOSE_OVERRIDE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/smoke_data_product_release.py --base-url http://skillra-api:8000 --token \"\$$SKILLRA_API_TOKEN\" --admin-token \"\$$SKILLRA_ADMIN_TOKEN\" --expected-runtime-env \"\$${SKILLRA_RUNTIME_ENV:-staging}\" --expected-public-base-url \"\$${SKILLRA_PUBLIC_BASE_URL:-https://staging.skillra.ru}\" --require-processed-s3 --processed-bucket \"\$$S3_BUCKET_PROCESSED\" --report data/metrics/data_product_release_staging.json"

seed-search:
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTHON) scripts/seed_meilisearch.py

minio-init:
	$(PYTHON) scripts/minio_init.py

minio-lifecycle-render:
	$(PYTHON) scripts/minio_lifecycle_policy.py --mode render --env-file $(ENV_FILE)

minio-lifecycle-render-prod:
	$(PYTHON) scripts/minio_lifecycle_policy.py --mode render --env-file $(PROD_ENV_FILE)

minio-lifecycle-check:
	$(PYTHON) scripts/minio_lifecycle_policy.py --mode check --env-file $(ENV_FILE)

minio-lifecycle-check-prod:
	$(PYTHON) scripts/minio_lifecycle_policy.py --mode check --env-file $(PROD_ENV_FILE)

minio-scope-smoke-local:
	docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/smoke_minio_scoped_access.py --endpoint-url http://minio:9000

minio-scope-smoke-prod:
	docker compose --env-file $(PROD_ENV_FILE) -f $(PROD_COMPOSE_FILE) --profile ops run --rm --no-deps pipeline_runner python scripts/smoke_minio_scoped_access.py --endpoint-url http://minio:9000

compose-validate:
	@set -e; \
	created_env=0; \
	created_prod=0; \
	created_staging=0; \
	cleanup() { \
		if [ $$created_env -eq 1 ]; then rm -f .env; fi; \
		if [ $$created_prod -eq 1 ]; then rm -f .env.prod; fi; \
		if [ $$created_staging -eq 1 ]; then rm -f .env.staging; fi; \
	}; \
	trap cleanup EXIT; \
	if [ ! -f .env ]; then cp .env.example .env; created_env=1; fi; \
	if [ ! -f .env.prod ]; then cp .env.prod.example .env.prod; created_prod=1; fi; \
	if [ ! -f .env.staging ]; then cp .env.staging.example .env.staging; created_staging=1; fi; \
	$(PYTHON) scripts/env_render.py --profile local --output .env.example --check; \
	$(PYTHON) scripts/env_render.py --profile prod --output .env.prod.example --check; \
	$(PYTHON) scripts/env_render.py --profile staging --output .env.staging.example --check; \
	docker compose -f infra/docker-compose.dev.yml --env-file .env config -q; \
	SKILLRA_COMPOSE_ENV_FILE=../.env.prod docker compose -f infra/docker-compose.prod.yml --env-file .env.prod --profile monitoring --profile storage --profile ops config -q; \
	SKILLRA_COMPOSE_ENV_FILE=../.env.staging SKILLRA_DATA_VOLUME_BASE=/var/lib/skillra-staging docker compose -p skillra-staging -f infra/docker-compose.prod.yml -f infra/docker-compose.staging.yml --env-file .env.staging --profile monitoring --profile storage --profile ops config -q

api-tests:
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTEST) -q apps/skillra_api/tests

bot-tests:
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(PYTEST) -q apps/telegram_bot/tests

all-tests: test api-tests bot-tests

mypy:
	PYTHONPATH="$(TEST_PYTHONPATH)$${PYTHONPATH:+:$${PYTHONPATH}}" $(MYPY) apps/skillra_api/src/skillra_api apps/telegram_bot/telegram_bot --ignore-missing-imports

ci: lint monitoring-check all-tests
