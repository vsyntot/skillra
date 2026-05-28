from __future__ import annotations

from pathlib import Path

from skillra_pda.ingest.date_semantics import build_cross_partition_duplicate_report, evaluate_csv_date_semantics


def test_evaluate_csv_date_semantics_reports_observed_range(tmp_path: Path) -> None:
    csv_path = tmp_path / "snapshot.csv"
    csv_path.write_text(
        "vacancy_id,published_at_iso\n1,2025-12-01\n2,2025-12-02T12:00:00+03:00\n",
        encoding="utf-8",
    )

    result = evaluate_csv_date_semantics(
        csv_path,
        requested_date_from="2025-12-01",
        requested_date_to="2025-12-02",
    )

    assert result["status"] == "passed"
    assert result["observed_published_at_from"] == "2025-12-01"
    assert result["observed_published_at_to"] == "2025-12-02"


def test_cross_partition_duplicate_report_counts_adjacent_overlap(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("vacancy_id\n1\n2\n", encoding="utf-8")
    second.write_text("vacancy_id\n2\n3\n", encoding="utf-8")

    report = build_cross_partition_duplicate_report(
        {
            "2025-12-01": first,
            "2025-12-02": second,
        }
    )

    assert report["raw_rows"] == 4
    assert report["unique_ids"] == 3
    assert report["duplicate_rows"] == 1
    assert report["adjacent_partition_overlap"]["2025-12-01..2025-12-02"] == 1
