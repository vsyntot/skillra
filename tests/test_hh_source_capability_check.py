from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import hh_source_capability_check as capability


def test_hh_source_capability_check_accepts_fixture_source(monkeypatch, tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.csv"
    report = tmp_path / "capability.json"
    fixture.write_text(
        "vacancy_id,title,published_at_iso\n1,Data Analyst,2025-12-01\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hh_source_capability_check.py",
            "--source-mode",
            "fixture",
            "--date-from",
            "2025-12-01",
            "--date-to",
            "2025-12-01",
            "--fixture-csv",
            str(fixture),
            "--output-dir",
            str(tmp_path),
            "--output-report",
            str(report),
            "--strict",
        ],
    )

    capability.main()

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["capability_status"] == "supported"
    assert payload["date_semantics"]["status"] == "passed"
    assert payload["source_capability_ref"]["source_mode"] == "fixture"
    assert payload["source_capability_ref"]["use_case"] == "historical_collection"
    assert payload["source_capability_ref"]["capability_status"] == "supported"
    assert payload["coverage_claim"] == "test_fixture_only"
    assert payload["closed_archived_coverage"] == "unproven"
    assert "fixture data is test-only" in payload["coverage_limitations"][0]
    assert payload["source_capability_ref"]["coverage_claim"] == "test_fixture_only"
    assert payload["registry"]["schema_version"] == 1


def test_hh_source_capability_check_rejects_full_archive_claim_without_archive_proof(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture.csv"
    report = tmp_path / "capability.json"
    fixture.write_text(
        "vacancy_id,title,published_at_iso\n1,Data Analyst,2025-12-01\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hh_source_capability_check.py",
            "--source-mode",
            "fixture",
            "--date-from",
            "2025-12-01",
            "--date-to",
            "2025-12-01",
            "--fixture-csv",
            str(fixture),
            "--output-dir",
            str(tmp_path),
            "--output-report",
            str(report),
            "--coverage-claim",
            "complete_hh_archive",
        ],
    )

    capability.main()

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["capability_status"] == "unsupported"
    assert any("complete_hh_archive requires closed_archived_coverage=included" in item for item in payload["errors"])
