from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import scripts.raw_hh_gate as raw_hh_gate
from scripts.raw_hh_gate import validate_local_raw_hh, validate_s3_raw_hh
from skillra_pda.ingest.source_registry import build_source_capability_ref


def _write_raw_run(storage_dir: Path, state: dict) -> None:
    if "source_capability_ref" not in state:
        use_case = (
            "historical_collection"
            if state.get("requested_date_from") and state.get("requested_date_to")
            else "current_snapshot"
        )
        state["source_capability_ref"] = build_source_capability_ref(
            source_mode="fixture" if use_case == "historical_collection" else "hh_html",
            use_case=use_case,
            capability_status="supported",
            evidence_type="test_fixture" if use_case == "historical_collection" else "registry",
            requested_date_from=state.get("requested_date_from"),
            requested_date_to=state.get("requested_date_to"),
            dataset_scope=state.get("dataset_scope"),
            salary_only=state.get("salary_only"),
        )
    paths = [
        "latest.csv",
        "state.json",
        "manifest.jsonl",
        state["snapshot_path"],
        state["delta_path"],
        state["parquet_snapshot_path"],
    ]
    for rel in paths:
        path = storage_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel == "state.json":
            path.write_text(json.dumps(state), encoding="utf-8")
        elif rel.endswith(".csv"):
            rows = [
                f"{index},Vacancy {index},https://hh.ru/vacancy/{index},2026-05-19\n"
                for index in range(1, int(state.get("row_count") or 0) + 1)
            ]
            path.write_text("vacancy_id,title,vacancy_url,published_at_iso\n" + "".join(rows), encoding="utf-8")
        else:
            path.write_text("data", encoding="utf-8")


def test_validate_local_raw_hh_passes(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 10,
        "new_count": 2,
        "removed_count": 1,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    _write_raw_run(storage_dir, state)

    result = validate_local_raw_hh(storage_dir, state, min_rows=1, max_removed_share=0.8)

    assert result["status"] == "passed"
    assert result["metrics"]["row_count"] == 10
    assert result["csv_quality"]["duplicate_count"] == 0
    assert result["collection_quality"]["status"] == "not_available"


def test_validate_local_raw_hh_fails_latest_checksum_mismatch(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 1,
        "new_count": 1,
        "removed_count": 0,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
        "sha256": "bad-sha",
    }
    _write_raw_run(storage_dir, state)
    (storage_dir / "latest.csv").write_text("vacancy_id,title\n1,A\n", encoding="utf-8")

    result = validate_local_raw_hh(storage_dir, state, min_rows=1, max_removed_share=0.8)

    assert result["status"] == "failed"
    assert any("sha256 mismatch" in failure for failure in result["failures"])


def test_validate_local_raw_hh_fails_on_low_rows(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 0,
        "new_count": 0,
        "removed_count": 0,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    _write_raw_run(storage_dir, state)

    result = validate_local_raw_hh(storage_dir, state, min_rows=1, max_removed_share=0.8)

    assert result["status"] == "failed"
    assert "row_count 0 < min_rows 1" in result["failures"]


def test_validate_local_raw_hh_fails_on_latest_row_count_mismatch(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 2,
        "new_count": 2,
        "removed_count": 0,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    _write_raw_run(storage_dir, state)
    (storage_dir / "latest.csv").write_text(
        "vacancy_id,title,vacancy_url,published_at_iso\n1,A,https://hh.ru/vacancy/1,2026-05-19\n",
        encoding="utf-8",
    )

    result = validate_local_raw_hh(storage_dir, state, min_rows=1, max_removed_share=0.8)

    assert result["status"] == "failed"
    assert "latest.csv row_count 1 != state row_count 2" in result["failures"]


def test_validate_local_raw_hh_requires_dataset_scope_metadata(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 10,
        "new_count": 0,
        "removed_count": 0,
    }
    _write_raw_run(storage_dir, state)

    result = validate_local_raw_hh(storage_dir, state, min_rows=1, max_removed_share=0.8)

    assert result["status"] == "failed"
    assert "dataset_scope must be all_vacancies or salary_disclosed" in result["failures"]
    assert "salary_only must be present as boolean" in result["failures"]


def test_validate_local_raw_hh_fails_on_critical_field_completeness(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 2,
        "new_count": 2,
        "removed_count": 0,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    _write_raw_run(storage_dir, state)
    (storage_dir / "latest.csv").write_text(
        "vacancy_id,title,vacancy_url,published_at_iso\n"
        "1,,https://hh.ru/vacancy/1,2026-05-19\n"
        "2,,https://hh.ru/vacancy/2,2026-05-19\n",
        encoding="utf-8",
    )

    result = validate_local_raw_hh(storage_dir, state, min_rows=1, max_removed_share=0.8)

    assert result["status"] == "failed"
    assert any("title_completeness" in failure for failure in result["failures"])


def test_validate_local_raw_hh_passes_date_semantics(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2025-12-01",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2025-12-01/snapshot.parquet",
        "latest_path": "latest.csv",
        "row_count": 2,
        "new_count": 2,
        "removed_count": 0,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
        "requested_date_from": "2025-12-01",
        "requested_date_to": "2025-12-01",
    }
    _write_raw_run(storage_dir, state)
    (storage_dir / "latest.csv").write_text(
        "vacancy_id,title,vacancy_url,published_at_iso\n"
        "1,A,https://hh.ru/vacancy/1,2025-12-01\n"
        "2,B,https://hh.ru/vacancy/2,2025-12-01T12:00:00+03:00\n",
        encoding="utf-8",
    )

    result = validate_local_raw_hh(
        storage_dir,
        state,
        min_rows=1,
        max_removed_share=0.8,
        require_date_semantics=True,
    )

    assert result["status"] == "passed"
    assert result["date_semantics"]["observed_published_at_from"] == "2025-12-01"


def test_validate_local_raw_hh_fails_date_semantics_out_of_window(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2025-12-01",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2025-12-01/snapshot.parquet",
        "latest_path": "latest.csv",
        "row_count": 2,
        "new_count": 2,
        "removed_count": 0,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
        "requested_date_from": "2025-12-01",
        "requested_date_to": "2025-12-01",
    }
    _write_raw_run(storage_dir, state)
    (storage_dir / "latest.csv").write_text(
        "vacancy_id,title,published_at_iso\n1,A,2025-12-01\n2,B,2026-05-25\n",
        encoding="utf-8",
    )

    result = validate_local_raw_hh(
        storage_dir,
        state,
        min_rows=1,
        max_removed_share=0.8,
        require_date_semantics=True,
    )

    assert result["status"] == "failed"
    assert result["date_semantics"]["out_of_window_count"] == 1
    assert any("date semantics failed" in failure for failure in result["failures"])


def test_validate_local_raw_hh_fails_on_zero_row_collection_shard(tmp_path: Path) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "collection_report_path": "collection_report.json",
        "row_count": 1,
        "new_count": 1,
        "removed_count": 0,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    _write_raw_run(storage_dir, state)
    (storage_dir / "collection_report.json").write_text(
        json.dumps({"status": "success", "shard_results": [{"records_collected": 0, "errors": []}]}),
        encoding="utf-8",
    )

    result = validate_local_raw_hh(storage_dir, state, min_rows=1, max_removed_share=0.8)

    assert result["status"] == "failed"
    assert "zero_row_shards 1 > max_zero_row_shards 0" in result["failures"]


def test_validate_s3_raw_hh_requires_run_scoped_objects(tmp_path: Path, monkeypatch) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 1,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    _write_raw_run(storage_dir, state)
    client = Mock()
    client.head_object.return_value = {}

    run_id = state["last_run_id"]
    payload_by_key: dict[str, bytes] = {}
    for rel in [
        "latest.csv",
        "state.json",
        "manifest.jsonl",
        state["snapshot_path"],
        state["delta_path"],
        state["parquet_snapshot_path"],
    ]:
        payload_by_key[f"runs/{run_id}/{rel}"] = (storage_dir / rel).read_bytes()
    pointer = {
        "run_id": run_id,
        "artifacts": [
            {
                "key": key,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
            for key, payload in payload_by_key.items()
        ],
    }

    def fake_download_bytes(_client, _bucket: str, key: str) -> bytes:
        if key == "latest_pointer.json":
            return json.dumps(pointer).encode("utf-8")
        return payload_by_key[key]

    monkeypatch.setattr(raw_hh_gate, "download_bytes", fake_download_bytes)

    result = validate_s3_raw_hh(client, "bucket", storage_dir, state)

    assert result["status"] == "passed"
    assert result["pointer_failures"] == []
    checked_keys = [call.kwargs["Key"] for call in client.head_object.call_args_list]
    assert "runs/2026-05-19T01-00-00Z/latest.csv" in checked_keys
    assert "latest_pointer.json" in checked_keys


def test_validate_s3_raw_hh_fails_on_pointer_checksum_mismatch(tmp_path: Path, monkeypatch) -> None:
    storage_dir = tmp_path / "raw" / "hh"
    state = {
        "last_run_id": "2026-05-19T01-00-00Z",
        "run_date": "2026-05-19",
        "snapshot_path": "snapshots/snapshot.csv",
        "delta_path": "deltas/delta.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2026-05-19/snapshot.parquet",
        "row_count": 1,
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    _write_raw_run(storage_dir, state)
    client = Mock()
    client.head_object.return_value = {}
    run_key = "runs/2026-05-19T01-00-00Z/latest.csv"
    pointer = {
        "run_id": state["last_run_id"],
        "artifacts": [
            {
                "key": run_key,
                "sha256": "bad-sha",
                "size_bytes": len(b"data"),
            }
        ],
    }

    def fake_download_bytes(_client, _bucket: str, key: str) -> bytes:
        if key == "latest_pointer.json":
            return json.dumps(pointer).encode("utf-8")
        return b"data"

    monkeypatch.setattr(raw_hh_gate, "download_bytes", fake_download_bytes)

    result = validate_s3_raw_hh(client, "bucket", storage_dir, state)

    assert result["status"] == "failed"
    assert any("sha256 mismatch" in failure for failure in result["pointer_failures"])
    assert any("missing artifact keys" in failure for failure in result["pointer_failures"])
