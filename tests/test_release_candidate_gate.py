from __future__ import annotations

from datetime import datetime, timezone

from scripts.release_candidate_gate import build_gate_markdown, default_output_path, slugify


def test_slugify_release_candidate_id() -> None:
    assert slugify("RC 2026.05.27 #1") == "rc-2026-05-27-1"


def test_default_output_path_uses_acceptance_reports() -> None:
    path = default_output_path("rc-1", now=datetime(2026, 5, 27, tzinfo=timezone.utc))

    assert str(path) == "reports/acceptance/2026-05-27_rc_rc-1.md"


def test_build_gate_markdown_contains_required_sprint037_checks() -> None:
    markdown = build_gate_markdown(
        rc_id="rc-1",
        ref="abc123",
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert "`make deploy-staging`" in markdown
    assert "`make smoke-api-staging`" in markdown
    assert "`make telegram-smoke-staging`" in markdown
    assert "[docs/rollback.md](docs/rollback.md)" in markdown


def test_build_gate_markdown_records_staging_and_prod_evidence() -> None:
    markdown = build_gate_markdown(
        rc_id="rc-1",
        ref="abc123",
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
        status="ready",
        staging_base_url="https://staging.skillra.ru",
        staging_dataset_run_id="run-staging",
        staging_bot_username="skillra_staging_bot",
        staging_smoke_reports=["reports/acceptance/staging.json"],
        production_deploy_command="make deploy-prod",
        production_smoke_reports=["reports/acceptance/prod.json"],
        approver="release-owner",
        promotion_decision="approved",
        residual_risks=["No real user traffic on staging yet."],
    )

    assert "**Status:** ready" in markdown
    assert "Staging base URL: https://staging.skillra.ru" in markdown
    assert "Staging dataset run id: run-staging" in markdown
    assert "Staging Telegram bot: skillra_staging_bot" in markdown
    assert "`reports/acceptance/staging.json`" in markdown
    assert "Production deploy command: make deploy-prod" in markdown
    assert "`reports/acceptance/prod.json`" in markdown
    assert "Promotion decision: approved" in markdown
    assert "No real user traffic on staging yet." in markdown
