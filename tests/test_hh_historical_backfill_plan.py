from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import hh_historical_backfill_plan as plan_script


def _write_report(path: Path, *, status: str = "supported") -> None:
    path.write_text(
        json.dumps(
            {
                "source_mode": "fixture",
                "capability_status": status,
                "requested_date_from": "2025-12-01",
                "requested_date_to": "2025-12-01",
                "requested_query": "python",
                "areas": [113],
                "dataset_scope": "all_vacancies",
                "salary_only": False,
                "coverage_claim": "retrievable_through_proven_source",
                "coverage_limitations": ["fixture"],
                "closed_archived_coverage": "test_fixture",
                "row_count": 1,
                "date_semantics": {"status": "passed"},
            }
        ),
        encoding="utf-8",
    )


def test_historical_backfill_plan_writes_planned_control_snapshot(monkeypatch, tmp_path: Path) -> None:
    report = tmp_path / "source_capability.json"
    output_report = tmp_path / "plan_report.json"
    _write_report(report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hh_historical_backfill_plan.py",
            "--source-mode",
            "fixture",
            "--date-from",
            "2025-12-01",
            "--date-to",
            "2025-12-01",
            "--source-capability-report",
            str(report),
            "--control-dir",
            str(tmp_path / "control"),
            "--backfill-id",
            "test",
            "--output-report",
            str(output_report),
        ],
    )

    plan_script.main()

    payload = json.loads(output_report.read_text(encoding="utf-8"))
    assert payload["status"] == "planned"
    assert payload["collection_allowed"] is True
    assert payload["summary"]["shard_count"] == 1
    assert (tmp_path / "control" / "test" / "job.json").exists()
    assert (tmp_path / "control" / "test" / "shards.jsonl").exists()


def test_historical_backfill_plan_blocks_without_supported_source(monkeypatch, tmp_path: Path) -> None:
    report = tmp_path / "source_capability.json"
    output_report = tmp_path / "plan_report.json"
    _write_report(report, status="unsupported")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hh_historical_backfill_plan.py",
            "--source-mode",
            "fixture",
            "--date-from",
            "2025-12-01",
            "--date-to",
            "2025-12-01",
            "--source-capability-report",
            str(report),
            "--control-dir",
            str(tmp_path / "control"),
            "--backfill-id",
            "test",
            "--output-report",
            str(output_report),
        ],
    )

    plan_script.main()

    payload = json.loads(output_report.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["collection_allowed"] is False
    assert any("capability_status" in item for item in payload["source_failures"])
    assert payload["summary"]["status_counts"]["blocked_source_capability"] == 1
