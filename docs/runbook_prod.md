# Production Runbook

Production uses `infra/docker-compose.prod.yml` and `.env.prod` rendered from
the env schema or external secret management.

## Deploy

```bash
make prod-up
make prod-migrate
make deploy-prod-smoke
```

## Logs

```bash
make prod-logs
make prod-logs-full
```

## Data Refresh

```bash
make prod-data-refresh
```

The refresh flow validates raw HH data, processes artifacts, syncs to S3 when
enabled, reloads the API and reconciles search indexes.

## Secrets

```bash
make secrets-check-prod
make secrets-rotate-prod
```

Use service-specific restarts after rotation and verify API readiness, web
availability and Telegram bot health.
