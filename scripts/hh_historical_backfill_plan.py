from __future__ import annotations

"""Create a durable plan for an HH historical backfill candidate."""

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from skillra_pda.ingest.historical_backfill_control import (  # noqa: E402
    HistoricalBackfillPlanningConfig,
    JsonBackfillStore,
    block_job_for_source_capability,
    default_backfill_id,
    plan_historical_backfill,
)
from skillra_pda.ingest.source_registry import (  # noqa: E402
    source_capability_ref_from_report,
    validate_source_capability_ref,
)

DEFAULT_CONTROL_DIR = Path("data") / "raw" / "hh" / "historical_control"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", required=True, help="Start date inclusive: YYYY-MM-DD.")
    parser.add_argument("--date-to", default="today", help="End date inclusive: YYYY-MM-DD or today.")
    parser.add_argument("--source-mode", default="hh_api")
    parser.add_argument("--backfill-id", default=None)
    parser.add_argument("--control-dir", type=Path, default=DEFAULT_CONTROL_DIR)
    parser.add_argument("--source-capability-report", type=Path, default=None)
    parser.add_argument("--areas", nargs="*", type=int, default=[113])
    parser.add_argument("--professional-roles", nargs="*", default=[])
    parser.add_argument("--experiences", nargs="*", default=[])
    parser.add_argument("--schedules", nargs="*", default=[])
    parser.add_argument("--employments", nargs="*", default=[])
    parser.add_argument("--split-professional-roles", nargs="*", default=[])
    parser.add_argument("--split-experiences", nargs="*", default=[])
    parser.add_argument("--split-schedules", nargs="*", default=[])
    parser.add_argument("--split-employments", nargs="*", default=[])
    parser.add_argument("--dataset-scope", default="all_vacancies")
    parser.add_argument("--salary-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--coverage-claim", default=None)
    parser.add_argument("--coverage-limitation", action="append", default=[])
    parser.add_argument("--closed-archived-coverage", default=None)
    parser.add_argument("--max-found-per-shard", type=int, default=1_800)
    parser.add_argument("--max-pages-per-shard", type=int, default=18)
    parser.add_argument("--min-time-window-minutes", type=int, default=60)
    parser.add_argument("--output-report", type=Path, default=None)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if the plan is blocked by source capability or config failures.",
    )
    return parser.parse_args()


def parse_iso_date(value: str) -> date:
    if value == "today":
        return datetime.now(timezone.utc).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    args = parse_args()
    date_from = parse_iso_date(args.date_from)
    date_to = parse_iso_date(args.date_to)
    report, source_ref, source_failures = load_source_capability(
        args.source_capability_report,
        source_mode=args.source_mode,
        dataset_scope=args.dataset_scope,
        salary_only=args.salary_only,
        areas=args.areas,
    )
    coverage_claim = args.coverage_claim or str(
        (report or {}).get("coverage_claim") or source_ref.get("coverage_claim") or "unproven_source_access"
    )
    coverage_limitations = list(args.coverage_limitation) or list(
        (report or {}).get("coverage_limitations") or source_ref.get("coverage_limitations") or []
    )
    closed_archived_coverage = args.closed_archived_coverage or str(
        (report or {}).get("closed_archived_coverage") or source_ref.get("closed_archived_coverage") or "unproven"
    )
    backfill_id = args.backfill_id or default_backfill_id(date_from, date_to, source_mode=args.source_mode)

    config = HistoricalBackfillPlanningConfig(
        backfill_id=backfill_id,
        source_mode=args.source_mode,
        requested_date_from=date_from,
        requested_date_to=date_to,
        areas=tuple(args.areas),
        professional_roles=tuple(args.professional_roles),
        experiences=tuple(args.experiences),
        schedules=tuple(args.schedules),
        employments=tuple(args.employments),
        split_professional_roles=tuple(args.split_professional_roles),
        split_experiences=tuple(args.split_experiences),
        split_schedules=tuple(args.split_schedules),
        split_employments=tuple(args.split_employments),
        dataset_scope=args.dataset_scope,
        salary_only=args.salary_only,
        coverage_claim=coverage_claim,
        coverage_limitations=tuple(coverage_limitations),
        closed_archived_coverage=closed_archived_coverage,
        source_capability_ref=source_ref or None,
        max_found_per_shard=args.max_found_per_shard,
        max_pages_per_shard=args.max_pages_per_shard,
        min_time_window_minutes=args.min_time_window_minutes,
    )
    job, shards = plan_historical_backfill(config)
    if source_failures:
        job, shards = block_job_for_source_capability(
            job,
            shards,
            reason="; ".join(source_failures),
        )
    store = JsonBackfillStore(args.control_dir)
    with store.lock(job.backfill_id):
        summary = store.save_snapshot(job, shards)

    payload: dict[str, Any] = {
        "status": "blocked" if source_failures else "planned",
        "backfill_id": job.backfill_id,
        "control_dir": str(args.control_dir),
        "job_path": str(store.job_path(job.backfill_id)),
        "shards_path": str(store.shards_path(job.backfill_id)),
        "summary_path": str(store.summary_path(job.backfill_id)),
        "source_capability_report": str(args.source_capability_report) if args.source_capability_report else None,
        "source_failures": source_failures,
        "summary": summary,
        "collection_allowed": not source_failures,
        "publish_allowed": False,
        "publish_block_reason": "quality gate has not accepted this candidate",
    }
    output_report = args.output_report or args.control_dir / job.backfill_id / "plan_report.json"
    write_json(output_report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and source_failures:
        raise SystemExit(1)


def load_source_capability(
    report_path: Path | None,
    *,
    source_mode: str,
    dataset_scope: str,
    salary_only: bool,
    areas: list[int],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    if report_path is None:
        return None, {}, ["source capability report is required before historical collection"]
    if not report_path.exists():
        return None, {}, [f"source capability report not found: {report_path}"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        return None, {}, [f"source capability report must be a JSON object: {report_path}"]
    source_ref = source_capability_ref_from_report(report, report_path=report_path)
    failures = [
        "source_capability_ref: " + failure
        for failure in validate_source_capability_ref(
            source_ref,
            expected_source_mode=source_mode,
            expected_use_case="historical_collection",
            expected_dataset_scope=dataset_scope,
            expected_salary_only=salary_only,
            expected_areas=areas,
            require_supported=True,
        )
    ]
    if report.get("capability_status") != "supported":
        failures.append(f"capability_status is {report.get('capability_status')!r}, expected 'supported'")
    date_semantics = report.get("date_semantics")
    if not isinstance(date_semantics, dict) or date_semantics.get("status") != "passed":
        failures.append("date_semantics.status must be 'passed'")
    if int(report.get("row_count") or 0) <= 0:
        failures.append("row_count must be positive")
    if str(report.get("coverage_claim") or source_ref.get("coverage_claim") or "").startswith("unproven"):
        failures.append("coverage_claim is unproven")
    return report, source_ref, failures


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    main()
