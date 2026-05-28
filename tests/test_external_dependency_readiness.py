from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.external_dependency_readiness import build_report, render_markdown

SCHEMA = """
groups:
  - name: Skillra API
    variables:
      SKILLRA_PUBLIC_BASE_URL:
        type: url
        required: [staging]
      SKILLRA_RUNTIME_ENV:
        type: string
        allowed: [local, staging, prod]
      SKILLRA_DATA_VOLUME_BASE:
        type: string
      SKILLRA_EVIDENCE_EXPLAINER_ENABLED:
        type: bool
      SKILLRA_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS:
        type: string
      SKILLRA_EVIDENCE_EXPLAINER_PROD_ENABLE_APPROVED:
        type: bool
  - name: Database and storage
    variables:
      DATABASE_URL:
        type: postgres_url
      POSTGRES_DB:
        type: string
      MINIO_BUCKET_RESUMES:
        type: string
      MINIO_BUCKET_REPORTS:
        type: string
      S3_BUCKET_RAW_HH:
        type: string
      S3_BUCKET_PROCESSED:
        type: string
      S3_BUCKET_BACKUPS:
        type: string
  - name: Telegram bot
    variables:
      TELEGRAM_BOT_USERNAME:
        type: string
      TELEGRAM_PROD_BOT_USERNAME:
        type: string
      SKILLRA_API_BASE_URL:
        type: url
      BOT_MODE:
        type: string
        allowed: [polling, webhook]
      TELEGRAM_WEBHOOK_URL:
        type: url
  - name: Billing
    variables:
      SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED:
        type: bool
      SKILLRA_BILLING_SANDBOX_PROVIDER_NAME:
        type: string
      SKILLRA_BILLING_SANDBOX_WEBHOOK_SECRET:
        type: string
        secret: true
      SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED:
        type: bool
"""


def _write(path: Path, payload: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.strip() + "\n", encoding="utf-8")
    return path


def _check_by_id(report: dict, check_id: str) -> dict:
    return next(check for check in report["checks"] if check["id"] == check_id)


def test_external_dependency_report_blocks_missing_staging_inputs(tmp_path: Path) -> None:
    schema = _write(tmp_path / "schema.yml", SCHEMA)

    report = build_report(
        repo_root=tmp_path,
        schema_path=schema,
        staging_env_file=Path(".env.staging"),
        prod_env_file=Path(".env.prod"),
        trend_report_path=Path("trend.json"),
        env={},
        generated_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    assert report["status"] == "blocked"
    assert _check_by_id(report, "staging_target")["status"] == "blocked"
    assert "STAGING_DEPLOY_HOST" in _check_by_id(report, "staging_target")["missing_inputs"]
    assert _check_by_id(report, "staging_env_contract")["status"] == "blocked"
    assert _check_by_id(report, "trend_claim_data")["status"] == "blocked"


def test_external_dependency_report_marks_ready_staging_but_keeps_trends_blocked(tmp_path: Path) -> None:
    schema = _write(tmp_path / "schema.yml", SCHEMA)
    _write(
        tmp_path / ".env.staging",
        """
        SKILLRA_PUBLIC_BASE_URL=https://staging.skillra.ru
        SKILLRA_RUNTIME_ENV=staging
        SKILLRA_DATA_VOLUME_BASE=/var/lib/skillra-staging
        DATABASE_URL=postgresql+asyncpg://skillra:skillra@postgres:5432/skillra_staging
        POSTGRES_DB=skillra_staging
        MINIO_BUCKET_RESUMES=skillra-staging-resumes
        MINIO_BUCKET_REPORTS=skillra-staging-reports
        S3_BUCKET_RAW_HH=skillra-staging-raw-hh
        S3_BUCKET_PROCESSED=skillra-staging-processed
        S3_BUCKET_BACKUPS=skillra-staging-backups
        TELEGRAM_BOT_USERNAME=skillra_staging_bot
        TELEGRAM_PROD_BOT_USERNAME=skillra_bot
        SKILLRA_API_BASE_URL=https://staging.skillra.ru
        BOT_MODE=polling
        SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED=1
        SKILLRA_BILLING_SANDBOX_PROVIDER_NAME=provider_sandbox
        SKILLRA_BILLING_SANDBOX_WEBHOOK_SECRET=provider-secret
        SKILLRA_BILLING_REAL_PROVIDER_LAUNCH_ENABLED=0
        SKILLRA_EVIDENCE_EXPLAINER_ENABLED=1
        SKILLRA_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS=123
        """,
    )
    _write(
        tmp_path / ".env.prod",
        """
        SKILLRA_EVIDENCE_EXPLAINER_PROD_ENABLE_APPROVED=0
        """,
    )
    _write(tmp_path / "reports" / "staging.json", '{"status": "ok"}')
    (tmp_path / "trend.json").write_text(
        json.dumps(
            {
                "status": "forward_accumulating",
                "claim_status": "blocked",
                "public_trends_allowed": False,
                "blocked_reasons": ["forward_current_snapshot_history_has_too_few_complete_weeks"],
                "forward_build": {"complete_weeks_observed": 0, "weeks_remaining": 8},
                "historical_gate": {"ready_run_count": 0},
            }
        ),
        encoding="utf-8",
    )

    report = build_report(
        repo_root=tmp_path,
        schema_path=schema,
        staging_env_file=Path(".env.staging"),
        prod_env_file=Path(".env.prod"),
        trend_report_path=Path("trend.json"),
        staging_smoke_reports=[Path("reports/staging.json")],
        approval_paths={"billing_provider": Path("reports/staging.json")},
        env={
            "DEPLOY_HOST": "prod-host",
            "STAGING_DEPLOY_HOST": "staging-host",
            "DEPLOY_REPO_PATH": "/opt/skillra_hse_pda",
            "STAGING_DEPLOY_REPO_PATH": "/opt/skillra_hse_pda_staging",
            "STAGING_DATA_BASE": "/var/lib/skillra-staging",
            "STAGING_COMPOSE_PROJECT": "skillra-staging",
        },
    )

    assert _check_by_id(report, "staging_target")["status"] == "ready"
    assert _check_by_id(report, "staging_env_contract")["status"] == "ready"
    assert _check_by_id(report, "staging_smoke_evidence")["status"] == "ready"
    assert _check_by_id(report, "billing_provider_sandbox")["status"] == "ready"
    assert _check_by_id(report, "trend_claim_data")["status"] == "blocked"
    assert report["status"] == "blocked"


def test_external_dependency_report_accepts_explicit_colocated_staging_target(tmp_path: Path) -> None:
    schema = _write(tmp_path / "schema.yml", SCHEMA)

    report = build_report(
        repo_root=tmp_path,
        schema_path=schema,
        staging_env_file=Path(".env.staging"),
        prod_env_file=Path(".env.prod"),
        env={
            "DEPLOY_HOST": "93.189.231.4",
            "STAGING_DEPLOY_HOST": "93.189.231.4",
            "STAGING_COLOCATE_ON_PROD": "1",
            "DEPLOY_REPO_PATH": "/opt/skillra_hse_pda",
            "STAGING_DEPLOY_REPO_PATH": "/opt/skillra_hse_pda_staging",
            "STAGING_DATA_BASE": "/var/lib/skillra-staging",
            "STAGING_COMPOSE_PROJECT": "skillra-staging",
        },
    )

    staging_target = _check_by_id(report, "staging_target")
    assert staging_target["status"] == "ready"
    assert "DEPLOY_HOST comparison=same_host_colocated" in staging_target["evidence"]


def test_render_markdown_includes_blocked_next_actions(tmp_path: Path) -> None:
    schema = _write(tmp_path / "schema.yml", SCHEMA)
    report = build_report(repo_root=tmp_path, schema_path=schema, env={})

    markdown = render_markdown(report)

    assert "# External Dependency Readiness Report" in markdown
    assert "| staging_target | P0 | blocked |" in markdown
    assert "Provision or select a non-production staging host/domain." in markdown
