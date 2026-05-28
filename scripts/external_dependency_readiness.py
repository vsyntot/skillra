#!/usr/bin/env python3
"""Build a machine-readable report for launch blockers outside code ownership."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from env_contract import is_placeholder, load_schema, parse_env_file
    from env_doctor import validate_env
except ModuleNotFoundError:  # pragma: no cover - used when imported as scripts.*
    from scripts.env_contract import is_placeholder, load_schema, parse_env_file
    from scripts.env_doctor import validate_env


REPORT_VERSION = "skillra_external_dependency_readiness.v1"
DEFAULT_SCHEMA = Path("infra/env/schema.yml")
DEFAULT_STAGING_ENV = Path(".env.staging")
DEFAULT_PROD_ENV = Path(".env.prod")
DEFAULT_TREND_REPORT = Path("reports/acceptance/sprint_045_trend_readiness.prod.json")
DEFAULT_OUTPUT_JSON = Path("reports/acceptance/external_dependency_readiness.local.json")
DEFAULT_OUTPUT_MD = Path("reports/acceptance/external_dependency_readiness.local.md")


@dataclass(frozen=True)
class ReadinessCheck:
    id: str
    title: str
    severity: str
    status: str
    evidence: list[str]
    missing_inputs: list[str]
    next_actions: list[str]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_value(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key)
    return default if value is None else str(value).strip()


def _redacted_state(value: str | None) -> str:
    if value is None or value == "":
        return "missing"
    if is_placeholder(value):
        return "placeholder"
    return "set"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _path_exists(raw_path: Path | None, repo_root: Path) -> bool:
    if raw_path is None:
        return False
    path = raw_path if raw_path.is_absolute() else repo_root / raw_path
    return path.exists()


def _relative_or_raw(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _staging_target_check(env: Mapping[str, str]) -> ReadinessCheck:
    deploy_host = _env_value(env, "DEPLOY_HOST", "93.189.231.4")
    staging_host = _env_value(env, "STAGING_DEPLOY_HOST")
    colocated = _truthy(env.get("STAGING_COLOCATE_ON_PROD"))
    deploy_repo = _env_value(env, "DEPLOY_REPO_PATH", "/opt/skillra_hse_pda")
    staging_repo = _env_value(env, "STAGING_DEPLOY_REPO_PATH", "/opt/skillra_hse_pda_staging")
    staging_data = _env_value(env, "STAGING_DATA_BASE", "/var/lib/skillra-staging")
    staging_project = _env_value(env, "STAGING_COMPOSE_PROJECT", "skillra-staging")

    missing: list[str] = []
    host_comparison = "not_proven"
    if staging_host and staging_host != deploy_host:
        host_comparison = "different"
    elif staging_host and staging_host == deploy_host and colocated:
        host_comparison = "same_host_colocated"
    evidence = [
        f"STAGING_DEPLOY_HOST={_redacted_state(staging_host)}",
        f"DEPLOY_HOST comparison={host_comparison}",
        f"STAGING_COLOCATE_ON_PROD={colocated}",
        f"staging_repo_path={'different' if staging_repo != deploy_repo else 'same_as_prod'}",
        f"staging_data_base={staging_data}",
        f"staging_compose_project={staging_project}",
    ]
    if not staging_host:
        missing.append("STAGING_DEPLOY_HOST")
    if staging_host and staging_host == deploy_host and not colocated:
        missing.append("non-production staging host or STAGING_COLOCATE_ON_PROD=1")
    if staging_repo == deploy_repo:
        missing.append("STAGING_DEPLOY_REPO_PATH distinct from DEPLOY_REPO_PATH")
    if staging_data.rstrip("/") == "/var/lib/skillra":
        missing.append("STAGING_DATA_BASE distinct from production data base")
    if staging_project == "skillra":
        missing.append("STAGING_COMPOSE_PROJECT distinct from production compose project")

    return ReadinessCheck(
        id="staging_target",
        title="Real isolated staging target",
        severity="P0",
        status="ready" if not missing else "blocked",
        evidence=evidence,
        missing_inputs=missing,
        next_actions=[
            "Provision or select a non-production staging host/domain.",
            "Export STAGING_DEPLOY_HOST and keep repo path, data base and compose project isolated.",
        ],
    )


def _staging_env_check(repo_root: Path, env_file: Path, schema_path: Path) -> tuple[ReadinessCheck, dict[str, str]]:
    env_path = env_file if env_file.is_absolute() else repo_root / env_file
    schema = schema_path if schema_path.is_absolute() else repo_root / schema_path
    if not env_path.exists():
        return (
            ReadinessCheck(
                id="staging_env_contract",
                title="Staging env and secret contract",
                severity="P0",
                status="blocked",
                evidence=[f"{_relative_or_raw(env_path, repo_root)} does not exist"],
                missing_inputs=[str(env_file)],
                next_actions=[
                    "Render a real .env.staging from staging secrets.",
                    "Run make env-check-staging before deploy-staging.",
                ],
            ),
            {},
        )

    values, _ = parse_env_file(env_path)
    try:
        errors, warnings = validate_env(load_schema(schema), "staging", env_path)
    except Exception as exc:  # noqa: BLE001 - this is an operator report, not app runtime
        errors = [str(exc)]
        warnings = []

    evidence = [
        f"env_file={_relative_or_raw(env_path, repo_root)}",
        f"validation_errors={len(errors)}",
        f"validation_warnings={len(warnings)}",
        f"telegram_bot_username={values.get('TELEGRAM_BOT_USERNAME', 'missing')}",
        f"public_base_url={values.get('SKILLRA_PUBLIC_BASE_URL', 'missing')}",
    ]
    return (
        ReadinessCheck(
            id="staging_env_contract",
            title="Staging env and secret contract",
            severity="P0",
            status="ready" if not errors else "blocked",
            evidence=evidence,
            missing_inputs=errors[:8],
            next_actions=[
                "Fix env-doctor errors without copying production secrets.",
                "Keep staging bot, buckets and database names distinct from production.",
            ],
        ),
        values,
    )


def _staging_smoke_check(repo_root: Path, smoke_reports: Sequence[Path]) -> ReadinessCheck:
    if not smoke_reports:
        return ReadinessCheck(
            id="staging_smoke_evidence",
            title="Real staging smoke evidence",
            severity="P0",
            status="blocked",
            evidence=["no staging smoke report paths were provided"],
            missing_inputs=[
                "make deploy-staging",
                "make health-staging",
                "make smoke-api-staging",
                "make cjm-smoke-staging",
                "make data-product-smoke-staging",
                "make telegram-smoke-staging",
            ],
            next_actions=["Run real staging smoke after host/secrets/bot are provisioned."],
        )

    missing_paths: list[str] = []
    evidence: list[str] = []
    for raw_path in smoke_reports:
        path = raw_path if raw_path.is_absolute() else repo_root / raw_path
        if path.exists():
            evidence.append(f"{_relative_or_raw(path, repo_root)}=present")
        else:
            evidence.append(f"{_relative_or_raw(path, repo_root)}=missing")
            missing_paths.append(str(raw_path))

    return ReadinessCheck(
        id="staging_smoke_evidence",
        title="Real staging smoke evidence",
        severity="P0",
        status="ready" if not missing_paths else "blocked",
        evidence=evidence,
        missing_inputs=missing_paths,
        next_actions=["Attach all staging smoke artifacts to the release-candidate gate."],
    )


def _billing_provider_check(
    staging_values: Mapping[str, str],
    approval_paths: Mapping[str, Path],
    repo_root: Path,
) -> ReadinessCheck:
    provider = staging_values.get("SKILLRA_BILLING_SANDBOX_PROVIDER_NAME", "")
    sandbox_enabled = _truthy(staging_values.get("SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED"))
    secret_state = _redacted_state(staging_values.get("SKILLRA_BILLING_SANDBOX_WEBHOOK_SECRET"))
    approval_path = approval_paths.get("billing_provider")
    approval_present = _path_exists(approval_path, repo_root)

    missing: list[str] = []
    if not provider or provider == "manual_invoice":
        missing.append("real provider sandbox name")
    if not sandbox_enabled:
        missing.append("SKILLRA_BILLING_SANDBOX_WEBHOOK_ENABLED=1 in staging")
    if secret_state != "set":
        missing.append("non-placeholder sandbox webhook secret")
    if not approval_present:
        missing.append("billing_provider approval/evidence file")

    return ReadinessCheck(
        id="billing_provider_sandbox",
        title="Real billing provider sandbox",
        severity="P0",
        status="ready" if not missing else "blocked",
        evidence=[
            f"sandbox_provider={provider or 'missing'}",
            f"sandbox_webhook_enabled={sandbox_enabled}",
            f"sandbox_webhook_secret={secret_state}",
            f"approval_evidence={'present' if approval_present else 'missing'}",
        ],
        missing_inputs=missing,
        next_actions=[
            "Select/acquire the real provider sandbox account.",
            "Attach provider/legal/accounting approval evidence before checkout E2E.",
        ],
    )


def _trend_claim_check(repo_root: Path, trend_report_path: Path) -> ReadinessCheck:
    path = trend_report_path if trend_report_path.is_absolute() else repo_root / trend_report_path
    payload = _load_json(path)
    public_allowed = bool(payload.get("public_trends_allowed"))
    forward_build = payload.get("forward_build") if isinstance(payload.get("forward_build"), dict) else {}
    historical_gate = payload.get("historical_gate") if isinstance(payload.get("historical_gate"), dict) else {}

    if not payload:
        evidence = [f"{_relative_or_raw(path, repo_root)}=missing"]
        missing = ["trend readiness report"]
    else:
        evidence = [
            f"report={_relative_or_raw(path, repo_root)}",
            f"status={payload.get('status', 'missing')}",
            f"claim_status={payload.get('claim_status', 'missing')}",
            f"public_trends_allowed={public_allowed}",
            f"complete_weeks_observed={forward_build.get('complete_weeks_observed')}",
            f"weeks_remaining={forward_build.get('weeks_remaining')}",
            f"historical_ready_run_count={historical_gate.get('ready_run_count')}",
        ]
        missing = (
            [] if public_allowed else list(payload.get("blocked_reasons") or ["public trend gate is not eligible"])
        )

    return ReadinessCheck(
        id="trend_claim_data",
        title="Public trend-claim data readiness",
        severity="P0",
        status="ready" if public_allowed else "blocked",
        evidence=evidence,
        missing_inputs=missing[:8],
        next_actions=[
            "Keep public trend claims blocked until the accepted source/date gate passes.",
            "Continue forward snapshot accumulation or approve a validated historical source.",
        ],
    )


def _explainer_beta_check(
    staging_values: Mapping[str, str],
    prod_values: Mapping[str, str],
    approval_paths: Mapping[str, Path],
    repo_root: Path,
) -> ReadinessCheck:
    staging_enabled = _truthy(staging_values.get("SKILLRA_EVIDENCE_EXPLAINER_ENABLED"))
    staging_allowlist = bool((staging_values.get("SKILLRA_EVIDENCE_EXPLAINER_ALLOWED_TELEGRAM_USER_IDS") or "").strip())
    prod_approved = _truthy(prod_values.get("SKILLRA_EVIDENCE_EXPLAINER_PROD_ENABLE_APPROVED"))
    approval_path = approval_paths.get("evidence_explainer_beta")
    approval_present = _path_exists(approval_path, repo_root)

    missing: list[str] = []
    if not staging_enabled:
        missing.append("staging controlled explainer flag")
    if not staging_allowlist:
        missing.append("staging explainer allowlist")
    if not prod_approved:
        missing.append("production beta approval flag")
    if not approval_present:
        missing.append("evidence_explainer_beta approval/evidence file")

    return ReadinessCheck(
        id="evidence_explainer_beta",
        title="Evidence explainer public beta approval",
        severity="P1",
        status="ready" if not missing else "blocked",
        evidence=[
            f"staging_enabled={staging_enabled}",
            f"staging_allowlist={'set' if staging_allowlist else 'missing'}",
            f"prod_enable_approved={prod_approved}",
            f"approval_evidence={'present' if approval_present else 'missing'}",
        ],
        missing_inputs=missing,
        next_actions=[
            "Run controlled staging explainer smoke before any production beta.",
            "Attach owner/scope/rollback/monitoring approval evidence.",
        ],
    )


def _b2b_approval_check(approval_paths: Mapping[str, Path], repo_root: Path) -> ReadinessCheck:
    approval_path = approval_paths.get("b2b_pilot_legal")
    approval_present = _path_exists(approval_path, repo_root)
    return ReadinessCheck(
        id="b2b_pilot_legal",
        title="B2B pilot legal/commercial approval",
        severity="P1",
        status="ready" if approval_present else "blocked",
        evidence=[f"approval_evidence={'present' if approval_present else 'missing'}"],
        missing_inputs=[] if approval_present else ["b2b_pilot_legal approval/evidence file"],
        next_actions=["Attach signed/approved pilot terms, DPA boundary and billing owner evidence before paid pilot."],
    )


def _summary(checks: Sequence[ReadinessCheck]) -> dict[str, int]:
    statuses = {"ready": 0, "blocked": 0}
    for check in checks:
        statuses[check.status] = statuses.get(check.status, 0) + 1
    statuses["total"] = len(checks)
    return statuses


def build_report(
    *,
    repo_root: Path,
    env: Mapping[str, str] | None = None,
    schema_path: Path = DEFAULT_SCHEMA,
    staging_env_file: Path = DEFAULT_STAGING_ENV,
    prod_env_file: Path = DEFAULT_PROD_ENV,
    trend_report_path: Path = DEFAULT_TREND_REPORT,
    staging_smoke_reports: Sequence[Path] = (),
    approval_paths: Mapping[str, Path] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    current_env = dict(os.environ if env is None else env)
    approvals = dict(approval_paths or {})
    staging_env_check, staging_values = _staging_env_check(repo_root, staging_env_file, schema_path)
    prod_env_path = prod_env_file if prod_env_file.is_absolute() else repo_root / prod_env_file
    prod_values, _ = parse_env_file(prod_env_path)
    checks = [
        _staging_target_check(current_env),
        staging_env_check,
        _staging_smoke_check(repo_root, staging_smoke_reports),
        _billing_provider_check(staging_values, approvals, repo_root),
        _trend_claim_check(repo_root, trend_report_path),
        _explainer_beta_check(staging_values, prod_values, approvals, repo_root),
        _b2b_approval_check(approvals, repo_root),
    ]
    overall_status = "blocked" if any(check.status == "blocked" for check in checks) else "ready"
    return {
        "report_version": REPORT_VERSION,
        "generated_at_utc": (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "status": overall_status,
        "summary": _summary(checks),
        "checks": [asdict(check) for check in checks],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    rows = []
    for check in report.get("checks", []):
        missing = ", ".join(check.get("missing_inputs") or []) or "-"
        evidence = "; ".join(check.get("evidence") or []) or "-"
        rows.append(
            "| {id} | {severity} | {status} | {missing} | {evidence} |".format(
                id=check.get("id", ""),
                severity=check.get("severity", ""),
                status=check.get("status", ""),
                missing=missing.replace("|", "/"),
                evidence=evidence.replace("|", "/"),
            )
        )
    next_actions: list[str] = []
    for check in report.get("checks", []):
        if check.get("status") != "blocked":
            continue
        for action in check.get("next_actions") or []:
            if action not in next_actions:
                next_actions.append(action)
    action_lines = "\n".join(f"- {action}" for action in next_actions) or "- None."
    summary = report.get("summary") or {}
    return f"""# External Dependency Readiness Report

**Generated at:** {report.get("generated_at_utc")}
**Status:** {report.get("status")}
**Report version:** `{report.get("report_version")}`

## Summary

- Ready checks: {summary.get("ready", 0)}
- Blocked checks: {summary.get("blocked", 0)}
- Total checks: {summary.get("total", 0)}

## Checks

| Check | Severity | Status | Missing inputs | Evidence |
|---|---:|---|---|---|
{chr(10).join(rows)}

## Next Actions

{action_lines}
"""


def _parse_key_paths(raw_values: Sequence[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for raw in raw_values:
        key, separator, value = raw.partition("=")
        if not separator or not key or not value:
            raise argparse.ArgumentTypeError("approval evidence must use key=path")
        parsed[key.strip()] = Path(value.strip())
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Skillra external dependency readiness evidence.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--staging-env-file", type=Path, default=DEFAULT_STAGING_ENV)
    parser.add_argument("--prod-env-file", type=Path, default=DEFAULT_PROD_ENV)
    parser.add_argument("--trend-report", type=Path, default=DEFAULT_TREND_REPORT)
    parser.add_argument("--staging-smoke-report", action="append", type=Path, default=[])
    parser.add_argument(
        "--approval-evidence",
        action="append",
        default=[],
        help="External approval evidence path in key=path form, e.g. billing_provider=reports/approval.md.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--fail-on-blocked", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    report = build_report(
        repo_root=repo_root,
        schema_path=args.schema,
        staging_env_file=args.staging_env_file,
        prod_env_file=args.prod_env_file,
        trend_report_path=args.trend_report,
        staging_smoke_reports=args.staging_smoke_report,
        approval_paths=_parse_key_paths(args.approval_evidence),
    )
    output_json = args.output_json if args.output_json.is_absolute() else repo_root / args.output_json
    output_md = args.output_md if args.output_md.is_absolute() else repo_root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary": report["summary"]}, ensure_ascii=False))
    if args.fail_on_blocked and report["status"] == "blocked":
        sys.exit(1)


if __name__ == "__main__":
    main()
