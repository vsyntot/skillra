from __future__ import annotations

"""Check whether a vacancy source can satisfy requested publication-date windows."""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from parser import hh_scraper  # noqa: E402
from parser.hh_api_source import HHApiSourceAdapter  # noqa: E402
from parser.job_source import CollectionRequest, FixtureJobSourceAdapter  # noqa: E402
from skillra_pda.ingest.date_semantics import evaluate_csv_date_semantics  # noqa: E402
from skillra_pda.ingest.source_registry import (  # noqa: E402
    build_source_capability_ref,
    capability_for,
    registry_payload,
)

DEFAULT_OUTPUT_DIR = Path("reports") / "source_capability"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-mode", choices=("hh_html", "hh_api", "fixture"), default="hh_html")
    parser.add_argument("--date-from", required=True, help="Requested publication date lower bound: YYYY-MM-DD.")
    parser.add_argument("--date-to", required=True, help="Requested publication date upper bound: YYYY-MM-DD.")
    parser.add_argument("--query", default=hh_scraper.DEFAULT_QUERY)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--areas", nargs="*", type=int, default=[113])
    parser.add_argument("--dataset-scope", default="all_vacancies")
    parser.add_argument("--salary-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fixture-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-report", type=Path, default=None)
    parser.add_argument(
        "--coverage-claim",
        default=None,
        help=(
            "Human/audit claim for the resulting dataset coverage, for example "
            "'retrievable_through_proven_source' or 'complete_hh_archive'. "
            "Defaults to a conservative source-specific claim."
        ),
    )
    parser.add_argument(
        "--coverage-limitation",
        action="append",
        default=[],
        help="Repeatable coverage limitation to record in the capability report.",
    )
    parser.add_argument(
        "--closed-archived-coverage",
        choices=("included", "not_included", "unproven", "test_fixture"),
        default="unproven",
        help="Whether the source evidence proves closed/archived vacancy coverage.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code when the source is unsupported or inconclusive.",
    )
    return parser.parse_args()


def adapter_for(source_mode: str):
    if source_mode == "fixture":
        return FixtureJobSourceAdapter()
    if source_mode == "hh_html":
        return hh_scraper.HHHtmlSourceAdapter()
    if source_mode == "hh_api":
        return HHApiSourceAdapter()
    raise ValueError(f"Unsupported source mode: {source_mode}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def default_coverage_claim(source_mode: str, capability_status: str) -> str:
    if source_mode == "fixture":
        return "test_fixture_only"
    if capability_status != "supported":
        return "unproven_source_access"
    return "retrievable_through_proven_source"


def default_coverage_limitations(
    *,
    source_mode: str,
    capability_status: str,
    closed_archived_coverage: str,
) -> list[str]:
    limitations: list[str] = []
    if capability_status != "supported":
        limitations.append("source capability did not pass; no historical coverage claim can be made")
    if source_mode == "fixture":
        limitations.append("fixture data is test-only and not a production HH coverage proof")
    if source_mode in {"hh_api", "hh_html"} and closed_archived_coverage != "included":
        limitations.append("closed/archived vacancy coverage is not proven by this report")
    if source_mode == "hh_api":
        limitations.append("dense HH API result windows require adaptive shard splitting before full collection")
    if source_mode == "hh_html":
        limitations.append(
            "HTML search coverage is brittle and must pass source/date gates for every historical window"
        )
    return limitations


def coverage_contract_failures(
    *,
    coverage_claim: str,
    closed_archived_coverage: str,
    capability_status: str,
) -> list[str]:
    failures: list[str] = []
    if coverage_claim == "complete_hh_archive" and closed_archived_coverage != "included":
        failures.append("coverage_claim=complete_hh_archive requires closed_archived_coverage=included")
    if coverage_claim == "complete_hh_archive" and capability_status != "supported":
        failures.append("coverage_claim=complete_hh_archive requires supported source capability")
    return failures


def main() -> None:
    args = parse_args()
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = args.output_dir / f"capability_{args.source_mode}_{stamp}.csv"
    collection_report_path = args.output_dir / f"collection_{args.source_mode}_{stamp}.json"
    output_report = args.output_report or args.output_dir / f"capability_{args.source_mode}_{stamp}.json"

    monotonic_start = time.monotonic()
    errors: list[str] = []
    row_count = 0
    date_semantics: dict[str, Any] | None = None
    registry_capability = capability_for(args.source_mode, "historical_collection")
    if registry_capability.get("status") == "unsupported":
        errors.append(f"source registry marks historical collection unsupported for {args.source_mode}")
    try:
        adapter = adapter_for(args.source_mode)
        result = adapter.collect(
            CollectionRequest(
                query=args.query,
                limit=args.limit,
                output_path=snapshot_path,
                dataset_scope=args.dataset_scope,
                salary_only=args.salary_only,
                delay=args.delay,
                max_pages=args.max_pages,
                area_ids=tuple(args.areas),
                date_from=f"{args.date_from}T00:00:00",
                date_to=f"{args.date_to}T23:59:59",
                fixture_csv_path=args.fixture_csv,
                collection_report_path=collection_report_path,
            )
        )
        row_count = result.report.row_count
        date_semantics = evaluate_csv_date_semantics(
            snapshot_path,
            requested_date_from=args.date_from,
            requested_date_to=args.date_to,
            max_unknown_share=0.05,
            max_out_of_window_share=0.0,
        )
    except Exception as exc:  # noqa: BLE001 - capability report must capture source failures
        errors.append(f"{exc.__class__.__name__}: {exc}")

    if errors:
        capability_status = "unsupported"
    elif row_count == 0:
        capability_status = "inconclusive"
        errors.append("source returned zero rows for the controlled request")
    elif date_semantics and date_semantics.get("status") == "passed":
        capability_status = "supported"
    else:
        capability_status = "unsupported"

    coverage_claim = args.coverage_claim or default_coverage_claim(args.source_mode, capability_status)
    coverage_limitations = list(args.coverage_limitation) or default_coverage_limitations(
        source_mode=args.source_mode,
        capability_status=capability_status,
        closed_archived_coverage=args.closed_archived_coverage,
    )
    errors.extend(
        coverage_contract_failures(
            coverage_claim=coverage_claim,
            closed_archived_coverage=args.closed_archived_coverage,
            capability_status=capability_status,
        )
    )
    if errors and capability_status == "supported":
        capability_status = "unsupported"

    finished = datetime.now(timezone.utc)
    source_capability_ref = build_source_capability_ref(
        source_mode=args.source_mode,
        use_case="historical_collection",
        capability_status=capability_status,
        evidence_type="capability_report",
        capability_report_path=output_report,
        requested_date_from=args.date_from,
        requested_date_to=args.date_to,
        dataset_scope=args.dataset_scope,
        salary_only=args.salary_only,
        areas=args.areas,
        coverage_claim=coverage_claim,
        coverage_limitations=coverage_limitations,
        closed_archived_coverage=args.closed_archived_coverage,
    )
    report = {
        "registry": registry_payload(),
        "source_mode": args.source_mode,
        "capability_status": capability_status,
        "source_capability_ref": source_capability_ref,
        "requested_query": args.query,
        "requested_date_from": args.date_from,
        "requested_date_to": args.date_to,
        "requested_limit": args.limit,
        "areas": args.areas,
        "dataset_scope": args.dataset_scope,
        "salary_only": args.salary_only,
        "coverage_claim": coverage_claim,
        "coverage_limitations": coverage_limitations,
        "closed_archived_coverage": args.closed_archived_coverage,
        "row_count": row_count,
        "snapshot_path": str(snapshot_path),
        "collection_report_path": str(collection_report_path),
        "date_semantics": date_semantics,
        "errors": errors,
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "duration_sec": round(time.monotonic() - monotonic_start, 2),
    }
    write_json(output_report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and capability_status != "supported":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
