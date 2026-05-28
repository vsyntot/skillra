# Secrets Inventory

Real secret values are excluded from git. Use generated env examples for shape
and `secrets/*.example` files for encrypted payload examples.

## Main Secrets

- `SKILLRA_API_TOKEN`: service token for trusted clients.
- `SKILLRA_ADMIN_TOKEN`: Admin token for privileged endpoints.
- `TELEGRAM_BOT_TOKEN`: Telegram bot token.
- `TELEGRAM_WEBHOOK_SECRET_TOKEN`: Telegram webhook secret.
- `DATABASE_URL` / `POSTGRES_PASSWORD`: database credentials.
- `MEILISEARCH_API_KEY`: search master key.
- `MINIO_ROOT_PASSWORD`, `MINIO_SECRET_KEY`, `S3_SECRET_ACCESS_KEY`,
  `S3_BACKUP_SECRET_ACCESS_KEY`: object-storage credentials.
- `GF_SECURITY_ADMIN_PASSWORD`: Grafana admin password.
- Billing webhook secrets when billing adapters are enabled.

## Rotation Runbook

1. Prepare the new value in a local secret channel or environment variable.
2. Run `make secrets-rotate-prod` for production rotation workflow.
3. Run `make secrets-check-prod` after rendering/provisioning.
4. Restart only the affected services.
5. Verify API health, bot health and any provider webhook affected by the
   rotated secret.

## SOPS Bootstrap

For a new encrypted payload, use the SOPS helper flow:

```bash
make secrets-bootstrap-prod
make secrets-check-prod
```

The encrypted production payload path is intentionally ignored by git; keep only
example files in the repository.
