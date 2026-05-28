from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


DEFAULT_COMMANDS = [
    "make lint",
    "make all-tests",
    "cd apps/skillra_web && npm run typecheck && npm run test && npm run lint && npm run build",
    "make compose-validate",
    "make deploy-staging",
    "make smoke-api-staging",
    "make cjm-smoke-staging",
    "make data-product-smoke-staging",
    "make telegram-smoke-staging",
]


def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "rc"


def default_output_path(rc_id: str, *, now: datetime | None = None) -> Path:
    current = now or datetime.now(timezone.utc)
    return Path("reports/acceptance") / f"{current:%Y-%m-%d}_rc_{slugify(rc_id)}.md"


def _format_value(value: str | None) -> str:
    return value if value else "_not recorded_"


def _format_list(values: Sequence[str] | None) -> str:
    recorded = [value for value in (values or []) if value]
    if not recorded:
        return "- _not recorded_"
    return "\n".join(f"- `{value}`" for value in recorded)


def build_gate_markdown(
    *,
    rc_id: str,
    ref: str,
    generated_at: datetime,
    rollback_doc: str = "docs/rollback.md",
    status: str = "pending",
    staging_base_url: str | None = None,
    staging_dataset_run_id: str | None = None,
    staging_bot_username: str | None = None,
    staging_smoke_reports: Sequence[str] | None = None,
    production_deploy_command: str | None = None,
    production_smoke_reports: Sequence[str] | None = None,
    approver: str | None = None,
    promotion_decision: str | None = None,
    residual_risks: Sequence[str] | None = None,
) -> str:
    commands = "\n".join(f"- [ ] `{command}`" for command in DEFAULT_COMMANDS)
    risks = "\n".join(f"- {risk}" for risk in residual_risks or []) or "- None recorded yet."
    return f"""# Release Candidate Gate - {rc_id}

**Generated at:** {generated_at.astimezone(timezone.utc).isoformat()}
**Git ref:** `{ref}`
**Rollback:** [{rollback_doc}]({rollback_doc})
**Status:** {status}

## Required Checks

{commands}

## Promotion Evidence

- Staging base URL: {_format_value(staging_base_url)}
- Staging dataset run id: {_format_value(staging_dataset_run_id)}
- Staging Telegram bot: {_format_value(staging_bot_username)}
- Production deploy command: {_format_value(production_deploy_command)}
- Approver: {_format_value(approver)}
- Promotion decision: {_format_value(promotion_decision)}

### Staging Smoke Report Paths

{_format_list(staging_smoke_reports)}

### Production Smoke Report Paths

{_format_list(production_smoke_reports)}

## Residual Risks

{risks}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a release candidate acceptance gate template.")
    parser.add_argument("--rc-id", required=True, help="Release candidate id, for example rc-2026-05-27-1.")
    parser.add_argument("--ref", default="HEAD", help="Git ref or commit SHA under promotion.")
    parser.add_argument("--output", type=Path, help="Output markdown path. Defaults to reports/acceptance.")
    parser.add_argument("--rollback-doc", default="docs/rollback.md")
    parser.add_argument(
        "--status",
        choices=("pending", "blocked", "ready", "promoted", "approved_exception"),
        default="pending",
    )
    parser.add_argument("--staging-base-url")
    parser.add_argument("--staging-dataset-run-id")
    parser.add_argument("--staging-bot-username")
    parser.add_argument("--staging-smoke-report", action="append", default=[])
    parser.add_argument("--production-deploy-command")
    parser.add_argument("--production-smoke-report", action="append", default=[])
    parser.add_argument("--approver")
    parser.add_argument("--promotion-decision")
    parser.add_argument("--residual-risk", action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or default_output_path(args.rc_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_gate_markdown(
            rc_id=args.rc_id,
            ref=args.ref,
            generated_at=datetime.now(timezone.utc),
            rollback_doc=args.rollback_doc,
            status=args.status,
            staging_base_url=args.staging_base_url,
            staging_dataset_run_id=args.staging_dataset_run_id,
            staging_bot_username=args.staging_bot_username,
            staging_smoke_reports=args.staging_smoke_report,
            production_deploy_command=args.production_deploy_command,
            production_smoke_reports=args.production_smoke_report,
            approver=args.approver,
            promotion_decision=args.promotion_decision,
            residual_risks=args.residual_risk,
        ),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
