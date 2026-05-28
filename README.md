# Skillra

Skillra is a career and job market navigator for IT and data roles. The product
turns vacancy data into a practical route for a user: target profile, market
view, skill gap, matching vacancies, career actions, progress tracking and
weekly Telegram digest.

The repository is a monorepo with the analytics core, data ingestion pipeline,
FastAPI backend, React web app, Telegram bot, digest worker and Docker
infrastructure.

## Product Scope

Skillra helps an early-career or switching specialist answer four questions:

- Which role, grade, geography and work format are realistic for me now?
- Which skills are most demanded in my target segment?
- Which gaps should I close first and why?
- Which vacancies and career actions should I use as evidence for the next step?

The current product surface includes:

- **Profile and onboarding**: target role, grade, geography, work mode, domain
  and current skills. Available in web and Telegram.
- **Market view**: segment size, salary quartiles, salary coverage, remote share,
  junior-friendly share, top skills and trust warnings.
- **Skill gap**: comparison of user skills against market demand, recommended
  skills, CSV/PDF export and short-lived public share links.
- **Vacancy search**: MeiliSearch-backed full-text search with DB fallback,
  filters, matched/missing skills and profile fit explanations.
- **Career plan**: target state, actions, action statuses, saved vacancies and
  generated recommendations from skill-gap evidence.
- **Trends**: salary, vacancy count, skill demand and career transition views
  from weekly market snapshots when trend gates allow public claims.
- **Weekly digest**: Telegram subscription, preview, history, chart attachment
  and standalone worker that claims due subscriptions.
- **Account and privacy controls**: per-user API keys, profile deletion, resume
  upload status and commercial entitlement state.
- **Organizations**: B2B organizations, cohorts, invites and aggregated cohort
  analytics with minimum-N controls.

## Technical Architecture

The system is split into stable runtime boundaries:

- `src/skillra_pda/` contains the analytics core: cleaning, feature engineering,
  market aggregation, persona/skill-gap logic, career path utilities, trend
  gates and S3 helpers.
- `parser/` contains HH.ru collection adapters. The daily refresh flow writes
  raw snapshots, deltas, manifests and the `latest.csv` pointer.
- `scripts/` contains pipeline, data quality gates, S3 sync/restore, smoke
  checks, deployment helpers, env rendering and secret-management utilities.
- `apps/skillra_api/` is the FastAPI service. It serves market/persona/search
  endpoints, user profiles, subscriptions, digest APIs, organizations, billing
  webhooks, admin reload/indexing controls and Prometheus metrics.
- `apps/skillra_web/` is the React/Vite SPA with generated OpenAPI types,
  TanStack Query, Tailwind CSS, Vitest and Playwright smoke tests.
- `apps/telegram_bot/` is the aiogram bot with onboarding, analytics commands,
  profile management, search, digest controls, API-key flow and admin commands.
- `apps/digest_worker/` is a separate worker that sends weekly digest messages
  and heartbeat/metrics files.
- `infra/` contains Dockerfiles, Docker Compose files, Caddy/nginx config,
  scheduler scripts and monitoring configuration for Prometheus, Loki, Grafana
  and Alertmanager.

Runtime dependencies:

- Postgres stores users, profiles, subscriptions, career plans, application
  outcomes, product events, data-run registry, organizations and vacancy
  snapshots.
- Redis is used for bot FSM state, callback context, pub/sub notifications and
  API reload fan-out.
- MeiliSearch serves vacancy and skill search. API falls back to Postgres where
  possible when the index is degraded.
- MinIO/S3 stores uploaded resumes, generated reports, raw HH artifacts,
  processed artifacts and backups. The API and pipeline still read local mounted
  parquet/CSV paths at runtime; S3 is archive/sync/restore storage.

## Data Flow

The primary data path is:

1. `scripts/hh_daily_refresh.py` collects HH vacancies into `data/raw/hh/`.
2. Raw quality gates validate row count, duplicate share, date semantics,
   required fields and collection errors.
3. `scripts/s3_sync_raw_hh.py` can archive raw artifacts to MinIO/S3.
4. `scripts/run_pipeline.py` cleans the raw CSV, builds features, market view,
   weekly snapshots, quality reports and `dataset_meta.json`.
5. Processed artifacts are written to `data/processed/runs/<run_id>/`, and a
   successful run updates `data/processed/latest/`.
6. `POST /v1/admin/reload-data` reloads the API `DataStore`, refreshes market
   snapshots and starts vacancy indexing.
7. Web, bot and digest worker consume the API.

Committed sample data:

- `data/raw/hh_moscow_it_2025_11_30.csv` is a static raw sample.
- `data/samples/*.csv` are small local/dev samples.
- Generated runtime data under `data/processed/`, `data/interim/`,
  `data/metrics/` and raw HH run outputs are ignored.

## Repository Map

```text
apps/
  skillra_api/      FastAPI backend, migrations, API tests
  skillra_web/      React/Vite web app, generated API types, web tests
  telegram_bot/     aiogram Telegram bot and bot tests
  digest_worker/    weekly digest sender
data/
  raw/              committed seed/sample raw data plus ignored runtime HH runs
  samples/          small CSV samples
infra/              Docker, compose, Caddy/nginx, monitoring, scheduler
parser/             HH collection adapters and field dictionary
requirements/       input requirements and pip-compile lock files
scripts/            pipeline, env, deploy, smoke, S3 and ops utilities
src/skillra_pda/    analytics package
tests/              core/pipeline/ops tests
docs/               handoff product, architecture and data docs
```

## Local Setup

Prerequisites:

- Python 3.11 is recommended. The Docker images and lock files are built for
  Python 3.11.
- Node.js 20+ and npm.
- Docker with Docker Compose.

Create the Python environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make bootstrap-ci
```

Create local env files:

```bash
make env-render
cp .env.example .env
```

Replace at least these values before running the full local stack:

- `SKILLRA_API_TOKEN`
- `SKILLRA_ADMIN_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_USERNAME`
- `MEILISEARCH_API_KEY`
- MinIO/Postgres passwords if the stack is shared

Run the local stack:

```bash
make compose-up
```

Useful local URLs:

- API health: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`
- Web app: `http://localhost:5173`
- MeiliSearch: `http://localhost:7700`
- MinIO console: `http://localhost:9001`

For direct development without Compose:

```bash
make api
cd apps/skillra_web && npm ci && npm run dev
make bot
```

The bot should use a separate BotFather test bot outside production.

## Build And Verification

Python:

```bash
make lint
make test
make api-tests
make bot-tests
make all-tests
```

Web:

```bash
cd apps/skillra_web
npm ci
npm run typecheck
npm run test
npm run lint
npm run build
```

Infrastructure:

```bash
make env-render-check
make compose-validate
make web-api-contract-check
```

Pipeline:

```bash
python scripts/run_pipeline.py
python scripts/validate_pipeline.py
```

Compose smoke:

```bash
make compose-smoke
```

## Environment And Secrets

`infra/env/schema.yml` is the source of truth for environment variables.
Generated examples are committed:

- `.env.example`
- `.env.prod.example`
- `.env.staging.example`

Regenerate them after changing the schema:

```bash
make env-render
make env-render-check
```

Real env files, decrypted values and SOPS payloads are not committed. Production
or staging secrets should be provisioned outside the repository and rendered
only on the target host. `secrets/prod.sops.yaml.example` documents the expected
encrypted-file shape without containing real values.

## Production Notes

Production Compose uses `infra/docker-compose.prod.yml` and publishes traffic
through Caddy on ports 80/443. API and bot service ports stay inside the Docker
network. Public endpoints are expected to be:

- `https://skillra.ru`
- `https://tg.skillra.ru/webhook` when Telegram webhook mode is enabled

Staging overlays production compose with `infra/docker-compose.staging.yml` and
uses isolated domains, database name, buckets and data volume base.

Operational helpers:

```bash
make prod-up
make prod-logs
make prod-migrate
make prod-data-refresh
make deploy-prod-smoke
```

## Handoff Checklist

Before transferring the repository:

- Run `make env-render-check` and keep env examples in sync with
  `infra/env/schema.yml`.
- Keep real `.env*`, SOPS files, generated reports, processed data,
  `node_modules/`, `.venv/` and IDE files out of the handoff package.
- Run the relevant checks from "Build And Verification" and record any known
  failures in the transfer note.
- Confirm `README.md`, `docs/architecture.md`, `docs/product.md` and
  `docs/feature_dictionary_hh.md` match the current code.
