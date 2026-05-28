from __future__ import annotations

import json
from parser import hh_scraper
from parser.job_source import CollectionRequest, FixtureJobSourceAdapter
from pathlib import Path

from scripts.hh_daily_refresh import run_scraper


def _write_fixture(path: Path) -> None:
    path.write_text("vacancy_id,title\n1,Data Analyst\n", encoding="utf-8")


def test_fixture_job_source_adapter_writes_snapshot_and_report(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.csv"
    output = tmp_path / "snapshot.csv"
    report_path = tmp_path / "report.json"
    _write_fixture(fixture)

    result = FixtureJobSourceAdapter().collect(
        CollectionRequest(
            query="data",
            limit=10,
            output_path=output,
            dataset_scope="all_vacancies",
            fixture_csv_path=fixture,
            collection_report_path=report_path,
        )
    )

    assert result.output_path == output
    assert output.read_text(encoding="utf-8") == fixture.read_text(encoding="utf-8")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source_mode"] == "fixture"
    assert report["row_count"] == 1
    assert report["sha256"]


def test_hh_daily_refresh_run_scraper_supports_fixture_source(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.csv"
    output = tmp_path / "snapshot.csv"
    report_path = tmp_path / "report.json"
    _write_fixture(fixture)

    run_scraper(
        output,
        "data",
        10,
        salary_only=False,
        dataset_scope="all_vacancies",
        source_mode="fixture",
        fixture_csv_path=fixture,
        collection_report_path=report_path,
    )

    assert output.exists()
    assert json.loads(report_path.read_text(encoding="utf-8"))["source_mode"] == "fixture"


def test_hh_html_source_adapter_wraps_existing_scraper(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "snapshot.csv"
    report_path = tmp_path / "report.json"

    def fake_scrape(**kwargs):
        Path(kwargs["output"]).write_text("vacancy_id,title\n1,Data Analyst\n", encoding="utf-8")
        return [object()]

    monkeypatch.setattr(hh_scraper, "scrape", fake_scrape)

    result = hh_scraper.HHHtmlSourceAdapter().collect(
        CollectionRequest(
            query="data",
            limit=10,
            output_path=output,
            dataset_scope="all_vacancies",
            collection_report_path=report_path,
        )
    )

    assert len(result.records) == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source_mode"] == "hh_html"
    assert report["row_count"] == 1
