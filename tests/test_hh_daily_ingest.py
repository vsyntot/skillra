import json
from pathlib import Path

import pandas as pd

from src.skillra_pda.ingest.hh_daily import (
    SCHEMA_VERSION,
    append_manifest_jsonl,
    build_failed_manifest_payload,
    build_manifest_payload,
    compute_delta,
    read_csv_columns,
    read_vacancy_ids,
    write_parquet_snapshot,
    write_state_json,
)


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    content = ",".join(headers) + "\n"
    content += "\n".join(",".join(row) for row in rows) + "\n"
    path.write_text(content, encoding="utf-8")


def test_read_vacancy_ids_from_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "vacancies.csv"
    _write_csv(
        csv_path,
        ["vacancy_id", "title"],
        [
            ["123", "One"],
            ["124", "Two"],
            ["124", "Duplicate"],
        ],
    )

    ids = read_vacancy_ids(str(csv_path))

    assert ids == {"123", "124"}


def test_compute_delta() -> None:
    new_ids, removed_ids = compute_delta({"1", "2"}, {"2", "3"})

    assert new_ids == {"3"}
    assert removed_ids == {"1"}


def test_write_state_and_manifest(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    manifest_path = tmp_path / "manifest.jsonl"
    payload = {
        "last_run_id": "2025-01-01",
        "row_count": 2,
    }

    write_state_json(str(state_path), payload)
    append_manifest_jsonl(str(manifest_path), payload)
    append_manifest_jsonl(str(manifest_path), {"last_run_id": "2025-01-02"})

    loaded_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert loaded_state == {
        **payload,
        "schema_version": SCHEMA_VERSION,
    }

    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 2
    assert json.loads(manifest_lines[0]) == payload
    assert json.loads(manifest_lines[1]) == {"last_run_id": "2025-01-02"}


def test_build_manifest_payload_includes_metadata(tmp_path: Path) -> None:
    csv_path = tmp_path / "snapshot.csv"
    _write_csv(
        csv_path,
        ["vacancy_id", "title"],
        [
            ["123", "One"],
            ["124", "Two"],
        ],
    )
    columns = read_csv_columns(str(csv_path))
    state_payload = {
        "last_run_id": "2025-01-01",
        "row_count": 2,
    }

    manifest_payload = build_manifest_payload(
        state_payload=state_payload,
        duration_sec=12.34,
        parquet_snapshot_path="snapshots_parquet/date=2025-01-01/snapshot_2025.parquet",
        snapshot_csv_path="snapshots/snapshot_2025.csv",
        columns=columns,
        schema_version=SCHEMA_VERSION,
    )

    assert manifest_payload["snapshot_csv"] == "snapshots/snapshot_2025.csv"
    assert manifest_payload["snapshot_parquet"] == ("snapshots_parquet/date=2025-01-01/snapshot_2025.parquet")
    assert manifest_payload["row_count"] == 2
    assert manifest_payload["columns"] == ["vacancy_id", "title"]
    assert manifest_payload["schema_version"] == SCHEMA_VERSION


def test_write_parquet_snapshot_from_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "snapshot.csv"
    _write_csv(
        csv_path,
        ["vacancy_id", "title"],
        [
            ["123", "One"],
            ["124", "Two"],
        ],
    )
    parquet_path = tmp_path / "snapshot.parquet"

    write_parquet_snapshot(str(csv_path), str(parquet_path))

    assert parquet_path.exists()
    frame = pd.read_parquet(parquet_path)
    assert frame.to_dict(orient="records") == [
        {"vacancy_id": "123", "title": "One"},
        {"vacancy_id": "124", "title": "Two"},
    ]


def test_append_failed_manifest_entry(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    missing_path = tmp_path / "missing.csv"

    try:
        read_vacancy_ids(str(missing_path))
    except FileNotFoundError as exc:
        payload = build_failed_manifest_payload(
            run_id="2025-01-03",
            run_date="2025-01-03",
            duration_sec=1.23,
            error=f"{exc.__class__.__name__}: {exc}",
            query="test",
            limit=1,
            schema_version=SCHEMA_VERSION,
        )
        append_manifest_jsonl(str(manifest_path), payload)

    manifest_lines = manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(manifest_lines) == 1
    manifest_payload = json.loads(manifest_lines[0])
    assert manifest_payload["status"] == "failed"
    assert manifest_payload["error"].startswith("FileNotFoundError:")
