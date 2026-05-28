# Security Model

Skillra separates user, service and admin access.

- **user API** access is represented by per-user API keys and must be scoped to
  the current user's profile, resume, subscriptions, career plan and account
  actions.
- **service token** access uses `SKILLRA_API_TOKEN` for trusted service-to-API
  calls from web local mode, bot, worker, pipeline and smoke tools.
- **Admin token** access uses `SKILLRA_ADMIN_TOKEN` for privileged reload,
  indexing, data-run, user-list and operational endpoints.
- Production and staging secrets are managed with **SOPS + age** or an external
  secret store. Real values are never committed.

Secret-management commands:

```bash
make secrets-check-prod
SECRET_KEY=TELEGRAM_BOT_TOKEN make secrets-rotate-prod
```

Run rotation only for a specific key when the value must be changed.

Security-sensitive changes should verify auth boundaries, PII handling, S3
bucket access, delete semantics and public URL/Telegram bot contour checks.
