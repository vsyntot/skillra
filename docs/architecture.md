# Skillra Architecture

This document describes the current repository and runtime architecture without
historical implementation notes.

## Components

### Analytics Core

Path: `src/skillra_pda/`

Responsibilities:

- clean raw vacancy data;
- extract role, grade, geography, work-mode, domain, salary and skill features;
- build market aggregates;
- compute persona and skill-gap outputs;
- evaluate data quality, trend readiness and rollback signals;
- provide S3/MinIO helpers for artifact sync and restore.

### Data Ingestion And Pipeline

Paths: `parser/`, `scripts/`, `infra/pipeline_runner.sh`

Responsibilities:

- collect HH vacancies through HTML/API adapters;
- maintain raw snapshots, deltas, `latest.csv`, `state.json` and manifests;
- validate raw artifacts before processing;
- produce processed parquet datasets, market view, weekly snapshots and metadata;
- sync raw and processed artifacts to MinIO/S3 when enabled;
- notify the API after a successful run.

### API

Path: `apps/skillra_api/`

Runtime: FastAPI, SQLAlchemy async, Alembic, Postgres, Redis, MeiliSearch,
MinIO/S3, Prometheus metrics.

Main router groups:

- health/readiness/auth checks;
- meta dictionaries;
- market summaries and trends;
- persona analysis, exports and share links;
- user profiles, resumes, API keys, account deletion and product events;
- vacancy and skill search;
- subscriptions, digest preview/chart/history;
- career plans, actions, saved vacancies and application outcomes;
- organizations, cohorts, invites and cohort analytics;
- billing webhooks and commercial state;
- admin reload, data-run registry and search indexing controls;
- metrics.

### Web App

Path: `apps/skillra_web/`

Runtime: React, Vite, TypeScript, Tailwind CSS, TanStack Query, Recharts,
Vitest, Playwright.

Main routes:

- `/login`;
- `/share/:token`;
- `/`;
- `/skill-gap`;
- `/market`;
- `/trends`;
- `/profile`;
- `/career-plan`;
- `/digest-history`;
- `/subscription`;
- `/search`;
- `/account`;
- `/organizations`.

The web client uses generated OpenAPI types from `apps/skillra_web/openapi.json`.
In local mode it can use a fallback service token; in staging/prod it expects a
user or team session token.

### Telegram Bot

Path: `apps/telegram_bot/`

Runtime: aiogram, httpx, Redis FSM storage, optional polling/webhook mode.

Main user commands:

- `/start`, `/help`, `/menu`, `/privacy`;
- `/market`, `/skillgap`, `/trends`, `/analyze`;
- `/profile`, `/settings`, `/delete_me`;
- `/search`, `/plan`, `/plan_recommend`;
- `/resume`, `/pdf`, `/csv`, `/share`;
- `/subscribe`, `/unsubscribe`, `/digest`, `/digest_history`;
- `/api_key`, `/account`, `/status`.

Admin commands are gated by `TELEGRAM_ADMIN_IDS`.

### Digest Worker

Path: `apps/digest_worker/`

The worker claims due weekly subscriptions from the API, sends digest messages
and charts through Telegram, acknowledges delivery and writes heartbeat/metrics
files for health checks.

### Infrastructure

Path: `infra/`

The local stack uses `infra/docker-compose.dev.yml`. Production uses
`infra/docker-compose.prod.yml`, and staging applies
`infra/docker-compose.staging.yml` as an override.

Key services:

- API, web, bot, digest worker and pipeline runner;
- Postgres, Redis, MeiliSearch and MinIO;
- Caddy/nginx ingress;
- Prometheus, Loki, Grafana, Alertmanager and exporters.

## Data Contracts

The serving API expects processed artifacts under `data/processed/latest/`:

- `hh_clean.parquet`;
- `hh_features.parquet`;
- `market_view.parquet`;
- `dataset_meta.json`;
- weekly market snapshots under `data/processed/market_snapshots/`.

Important feature columns:

- vacancy id: `hh_vacancy_id`, `vacancy_id` or `id`;
- title: `title` or `name`;
- URL: `vacancy_url`, `url` or `hh_url`;
- dimensions: `primary_role`, `grade_final`, `city_tier`, `work_mode`, `domain`;
- geography: `country`, `region`, `city_normalized`, `geo_scope`;
- salary: `salary_from`, `salary_to`, `salary_mid_rub_capped`,
  `salary_disclosed`;
- skills: `has_*` and `skill_*` boolean columns.

`dataset_meta.json` carries lineage and trust metadata: run id, generation time,
row counts, source kind, source date semantics, quality reports and trend gates.

## Environment Contract

`infra/env/schema.yml` is the source of truth. `.env.example`,
`.env.prod.example` and `.env.staging.example` are generated from it by
`scripts/env_render.py`.

The API and bot use separate service/admin credentials:

- `SKILLRA_API_TOKEN`;
- `SKILLRA_ADMIN_TOKEN`;
- per-user API keys for web sessions.

Production/staging real values must not be committed. Keep decrypted `.env*`
files and SOPS payloads outside git.

## Operational Flows

### Local Development

1. Create `.venv` with Python 3.11.
2. Run `make bootstrap-ci`.
3. Run `make env-render` and copy `.env.example` to `.env`.
4. Fill tokens.
5. Run `make compose-up`.
6. Check API health and web app.

### Data Refresh

1. Scheduler or operator starts `infra/pipeline_runner.sh`.
2. Optional HH refresh writes raw artifacts.
3. Raw quality gate blocks bad input.
4. Processing writes a versioned run and updates `latest`.
5. Optional S3 sync archives processed artifacts.
6. API admin reload activates the new data.
7. Search index is reconciled.
8. Bot subscribers can be notified about market updates.

### Search Indexing

The API can auto-seed `vacancy_snapshots` and configure MeiliSearch indexes at
startup. Admin reload can trigger incremental indexing. If MeiliSearch is
unavailable, search state is reported as degraded/fallback where possible.

### Deployment

Production deployment helpers live in `scripts/deploy_prod.sh` and Makefile
targets. After deployment, run health/smoke checks against API, web and
Telegram bot.
