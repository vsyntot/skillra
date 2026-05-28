# Skillra API

FastAPI backend for Skillra. The service exposes market analytics, persona and
skill-gap analysis, user profiles, vacancy search, career plans, subscriptions,
digests, organizations, billing webhooks, admin data reload and metrics.

## Structure

- `src/skillra_api/main.py` - application factory, middleware, lifespan and
  router registration.
- `src/skillra_api/config.py` - environment-driven settings.
- `src/skillra_api/routers/` - API endpoint groups.
- `src/skillra_api/services/` - search, indexing, digest, organizations,
  evidence, storage and business services.
- `src/skillra_api/db/` - SQLAlchemy models and session helpers.
- `alembic/` - database migrations.
- `tests/` - API/unit tests.

## Local Run

From the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make bootstrap-ci
make env-render
cp .env.example .env
make api
```

The service reads `.env`, then serves:

- `GET /health`
- `GET /v1/health`
- `GET /v1/ready`
- OpenAPI docs at `/docs`

## Database

When `DATABASE_URL` is configured, the API uses Postgres and validates Alembic
head status in readiness output.

Apply migrations:

```bash
cd apps/skillra_api
alembic upgrade head
```

Compose runs the `migrator` service automatically before API readiness.

## Data

The API loads processed parquet artifacts from `SKILLRA_DATA_DIR`, defaulting to
`data/processed/latest`. Required runtime artifacts are:

- `hh_features.parquet`
- `market_view.parquet`
- `dataset_meta.json`

If data is missing, health/readiness surfaces a degraded state instead of hiding
the problem.

## Checks

```bash
make api-tests
make lint
```

For contract changes that affect the web client, regenerate and check OpenAPI
types from `apps/skillra_web`.
