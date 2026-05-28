from pathlib import Path

from scripts.env_doctor import validate_env

MINIO_SCHEMA = {
    "groups": [
        {
            "name": "Search and storage",
            "variables": {
                "MINIO_ACCESS_KEY": {"type": "string"},
                "S3_ACCESS_KEY_ID": {"type": "string"},
                "S3_BACKUP_ACCESS_KEY_ID": {"type": "string"},
            },
        }
    ]
}

BOT_SCHEMA = {
    "groups": [
        {
            "name": "Skillra API",
            "variables": {
                "SKILLRA_PUBLIC_BASE_URL": {"type": "url", "required": ["prod"]},
                "SKILLRA_RUNTIME_ENV": {"type": "string", "allowed": ["local", "staging", "prod"]},
                "SKILLRA_DATA_VOLUME_BASE": {"type": "string"},
            },
        },
        {
            "name": "Database and storage",
            "variables": {
                "DATABASE_URL": {"type": "postgres_url"},
                "POSTGRES_DB": {"type": "string"},
                "MINIO_BUCKET_RESUMES": {"type": "string"},
                "MINIO_BUCKET_REPORTS": {"type": "string"},
                "S3_BUCKET_RAW_HH": {"type": "string"},
                "S3_BUCKET_PROCESSED": {"type": "string"},
                "S3_BUCKET_BACKUPS": {"type": "string"},
            },
        },
        {
            "name": "Telegram bot",
            "variables": {
                "TELEGRAM_BOT_USERNAME": {"type": "string"},
                "TELEGRAM_BOT_TOKEN": {"type": "string", "secret": True},
                "BOT_MODE": {"type": "string", "allowed": ["polling", "webhook"]},
                "SKILLRA_API_BASE_URL": {"type": "url", "required": ["local", "staging", "prod"]},
                "TELEGRAM_WEBHOOK_URL": {"type": "url"},
            },
        },
        {
            "name": "Billing",
            "variables": {
                "SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED": {"type": "bool"},
                "SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED": {"type": "bool"},
            },
        },
    ]
}


def _write_env(path: Path, payload: str) -> Path:
    path.write_text(payload.strip() + "\n", encoding="utf-8")
    return path


def test_env_doctor_rejects_duplicate_minio_role_users_in_prod(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env.prod",
        """
        MINIO_ACCESS_KEY=skillra-app
        S3_ACCESS_KEY_ID=skillra-app
        S3_BACKUP_ACCESS_KEY_ID=skillra-backup
        """,
    )

    errors, warnings = validate_env(MINIO_SCHEMA, "prod", env_file)

    assert warnings == []
    assert errors == ["MINIO_ACCESS_KEY and S3_ACCESS_KEY_ID must be distinct for least-privilege MinIO access"]


def test_env_doctor_warns_on_duplicate_minio_role_users_in_local(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env",
        """
        MINIO_ACCESS_KEY=skillra-app
        S3_ACCESS_KEY_ID=skillra-app
        S3_BACKUP_ACCESS_KEY_ID=skillra-backup
        """,
    )

    errors, warnings = validate_env(MINIO_SCHEMA, "local", env_file)

    assert errors == []
    assert warnings == ["MINIO_ACCESS_KEY and S3_ACCESS_KEY_ID must be distinct for least-privilege MinIO access"]


def test_env_doctor_rejects_official_bot_outside_prod_runtime(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env",
        """
        SKILLRA_RUNTIME_ENV=local
        TELEGRAM_BOT_USERNAME=skillra_bot
        SKILLRA_API_BASE_URL=http://skillra-api:8000
        """,
    )

    errors, warnings = validate_env(BOT_SCHEMA, "local", env_file)

    assert warnings == []
    assert errors == ["@skillra_bot cannot be used outside prod runtime"]


def test_env_doctor_accepts_official_bot_in_prod_runtime(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env.prod",
        """
        SKILLRA_RUNTIME_ENV=prod
        SKILLRA_PUBLIC_BASE_URL=https://skillra.ru
        TELEGRAM_BOT_USERNAME=skillra_bot
        TELEGRAM_BOT_TOKEN=real-token
        BOT_MODE=polling
        SKILLRA_API_BASE_URL=http://skillra-api:8000
        """,
    )

    errors, warnings = validate_env(BOT_SCHEMA, "prod", env_file)

    assert warnings == []
    assert errors == []


def test_env_doctor_rejects_wrong_prod_bot_domains(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env.prod",
        """
        SKILLRA_RUNTIME_ENV=prod
        SKILLRA_PUBLIC_BASE_URL=https://staging.skillra.ru
        TELEGRAM_BOT_USERNAME=skillra_bot
        TELEGRAM_BOT_TOKEN=real-token
        BOT_MODE=webhook
        SKILLRA_API_BASE_URL=http://localhost:8000
        TELEGRAM_WEBHOOK_URL=https://example.com/webhook
        """,
    )

    errors, warnings = validate_env(BOT_SCHEMA, "prod", env_file)

    assert warnings == []
    assert "SKILLRA_PUBLIC_BASE_URL must be https://skillra.ru in prod" in errors
    assert "TELEGRAM_WEBHOOK_URL cannot be example.com when BOT_MODE=webhook" in errors
    assert "TELEGRAM_WEBHOOK_URL must be https://tg.skillra.ru/webhook in prod webhook mode" in errors
    assert "@skillra_bot cannot use local SKILLRA_API_BASE_URL" in errors


def test_env_doctor_rejects_staging_pointing_to_production(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env.staging",
        """
        SKILLRA_RUNTIME_ENV=staging
        SKILLRA_DATA_VOLUME_BASE=/var/lib/skillra
        SKILLRA_PUBLIC_BASE_URL=https://skillra.ru
        DATABASE_URL=postgresql+asyncpg://skillra:skillra@postgres:5432/skillra
        POSTGRES_DB=skillra
        MINIO_BUCKET_RESUMES=skillra-resumes
        MINIO_BUCKET_REPORTS=skillra-reports
        S3_BUCKET_RAW_HH=skillra-raw-hh
        S3_BUCKET_PROCESSED=skillra-processed
        S3_BUCKET_BACKUPS=skillra-backups
        TELEGRAM_BOT_USERNAME=skillra_bot
        TELEGRAM_BOT_TOKEN=real-token
        BOT_MODE=webhook
        SKILLRA_API_BASE_URL=http://skillra-api:8000
        TELEGRAM_WEBHOOK_URL=https://tg.skillra.ru/webhook
        """,
    )

    errors, warnings = validate_env(BOT_SCHEMA, "staging", env_file)

    assert warnings == []
    assert "SKILLRA_PUBLIC_BASE_URL must not point to production in staging" in errors
    assert "TELEGRAM_WEBHOOK_URL must not point to production in staging" in errors
    assert "TELEGRAM_WEBHOOK_URL must be https://tg.staging.skillra.ru/webhook in staging webhook mode" in errors
    assert "@skillra_bot cannot be used outside prod runtime" in errors
    assert "SKILLRA_DATA_VOLUME_BASE must not use the production value in staging" in errors
    assert "DATABASE_URL must not point to the production database name in staging" in errors
    assert "POSTGRES_DB must not use the production value in staging" in errors
    assert "S3_BUCKET_PROCESSED must not use the production value in staging" in errors


def test_env_doctor_accepts_isolated_staging_bot(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env.staging",
        """
        SKILLRA_RUNTIME_ENV=staging
        SKILLRA_DATA_VOLUME_BASE=/var/lib/skillra-staging
        SKILLRA_PUBLIC_BASE_URL=https://staging.skillra.ru
        DATABASE_URL=postgresql+asyncpg://skillra:skillra@postgres:5432/skillra_staging
        POSTGRES_DB=skillra_staging
        MINIO_BUCKET_RESUMES=skillra-staging-resumes
        MINIO_BUCKET_REPORTS=skillra-staging-reports
        S3_BUCKET_RAW_HH=skillra-staging-raw-hh
        S3_BUCKET_PROCESSED=skillra-staging-processed
        S3_BUCKET_BACKUPS=skillra-staging-backups
        TELEGRAM_BOT_USERNAME=skillra_staging_bot
        TELEGRAM_BOT_TOKEN=real-token
        BOT_MODE=webhook
        SKILLRA_API_BASE_URL=http://skillra-api:8000
        TELEGRAM_WEBHOOK_URL=https://tg.staging.skillra.ru/webhook
        """,
    )

    errors, warnings = validate_env(BOT_SCHEMA, "staging", env_file)

    assert warnings == []
    assert errors == []


def test_env_doctor_rejects_prod_billing_launch_flags_without_approval(tmp_path: Path) -> None:
    env_file = _write_env(
        tmp_path / ".env.prod",
        """
        SKILLRA_RUNTIME_ENV=prod
        SKILLRA_PUBLIC_BASE_URL=https://skillra.ru
        TELEGRAM_BOT_USERNAME=skillra_bot
        TELEGRAM_BOT_TOKEN=real-token
        BOT_MODE=polling
        SKILLRA_API_BASE_URL=http://skillra-api:8000
        SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED=1
        SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED=true
        """,
    )

    errors, warnings = validate_env(BOT_SCHEMA, "prod", env_file)

    assert warnings == []
    assert "SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED must not be enabled in prod" in errors
    assert "SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED must remain disabled until launch approval" in errors
