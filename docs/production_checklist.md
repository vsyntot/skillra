# Production Checklist

Before production rollout:

- `.env.prod` is rendered from `infra/env/schema.yml` and contains real values.
- `make secrets-check-prod` passes.
- `make secrets-rotate-prod` is available for emergency rotation.
- `make compose-validate` passes.
- API migrations apply with `make prod-migrate`.
- Processed data exists under the production data volume.
- API `/health` and `/v1/ready` are healthy.
- Web app is reachable through Caddy.
- Telegram bot uses the production username only in production runtime.
- Digest worker heartbeat is fresh.
- Monitoring profile starts and Prometheus/Grafana are reachable.

After rollout:

- Run `make deploy-prod-smoke`.
- Check API, web, Telegram and digest logs.
- Confirm data-run and search-index status from admin endpoints.
