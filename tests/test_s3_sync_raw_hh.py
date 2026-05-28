from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from scripts.s3_sync_raw_hh import (
    RawHHArtifact,
    build_latest_pointer,
    build_raw_hh_artifacts,
    s3_object_exists,
    sync_latest_pointer,
    sync_raw_hh_artifacts,
)


def test_build_raw_hh_artifacts_uses_state_paths() -> None:
    storage_dir = Path("/data/raw/hh")
    state = {
        "last_run_id": "2025-02-10T01-00-00Z",
        "run_date": "2025-02-10",
        "snapshot_path": "snapshots/snapshot_2025-02-10T01-00-00Z.csv",
        "delta_path": "deltas/delta_2025-02-10T01-00-00Z.csv",
        "latest_path": "latest.csv",
        "parquet_snapshot_path": "snapshots_parquet/date=2025-02-10/snapshot_2025-02-10T01-00-00Z.parquet",
        "collection_report_path": "collection_reports/collection_2025-02-10T01-00-00Z.json",
    }

    artifacts = build_raw_hh_artifacts(storage_dir, state)
    keys = [artifact.key for artifact in artifacts]

    assert keys[:7] == [
        "runs/2025-02-10T01-00-00Z/latest.csv",
        "runs/2025-02-10T01-00-00Z/state.json",
        "runs/2025-02-10T01-00-00Z/manifest.jsonl",
        "runs/2025-02-10T01-00-00Z/snapshots/snapshot_2025-02-10T01-00-00Z.csv",
        "runs/2025-02-10T01-00-00Z/deltas/delta_2025-02-10T01-00-00Z.csv",
        "runs/2025-02-10T01-00-00Z/snapshots_parquet/date=2025-02-10/snapshot_2025-02-10T01-00-00Z.parquet",
        "runs/2025-02-10T01-00-00Z/collection_reports/collection_2025-02-10T01-00-00Z.json",
    ]
    assert keys[7:] == [
        "latest.csv",
        "state.json",
        "manifest.jsonl",
        "snapshots/snapshot_2025-02-10T01-00-00Z.csv",
        "deltas/delta_2025-02-10T01-00-00Z.csv",
        "snapshots_parquet/date=2025-02-10/snapshot_2025-02-10T01-00-00Z.parquet",
        "collection_reports/collection_2025-02-10T01-00-00Z.json",
    ]


def test_build_raw_hh_artifacts_falls_back_to_parquet_layout() -> None:
    storage_dir = Path("/data/raw/hh")
    state = {
        "last_run_id": "2025-02-11T01-00-00Z",
        "run_date": "2025-02-11",
        "snapshot_path": "snapshots/snapshot_2025-02-11T01-00-00Z.csv",
        "delta_path": "deltas/delta_2025-02-11T01-00-00Z.csv",
    }

    artifacts = build_raw_hh_artifacts(storage_dir, state)
    assert artifacts[5].key == (
        "runs/2025-02-11T01-00-00Z/snapshots_parquet/date=2025-02-11/" "snapshot_2025-02-11T01-00-00Z.parquet"
    )
    assert artifacts[-1].key == "snapshots_parquet/date=2025-02-11/snapshot_2025-02-11T01-00-00Z.parquet"


def test_s3_object_exists_handles_missing() -> None:
    client = Mock()
    client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    assert s3_object_exists(client, "bucket", "missing") is False


def test_sync_raw_hh_artifacts_skips_existing_objects(tmp_path: Path) -> None:
    client = Mock()
    client.head_object.return_value = {}

    path = tmp_path / "latest.csv"
    path.write_text("data", encoding="utf-8")
    artifacts = [RawHHArtifact(path, "latest.csv")]

    sync_raw_hh_artifacts(client, "bucket", artifacts, dry_run=False, overwrite=False)
    client.upload_file.assert_not_called()


def test_sync_raw_hh_artifacts_uploads_when_missing(tmp_path: Path) -> None:
    client = Mock()
    client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    path = tmp_path / "latest.csv"
    path.write_text("data", encoding="utf-8")
    artifacts = [RawHHArtifact(path, "latest.csv")]

    sync_raw_hh_artifacts(client, "bucket", artifacts, dry_run=False, overwrite=False)
    client.upload_file.assert_called_once_with(str(path), "bucket", "latest.csv")


def test_sync_raw_hh_artifacts_dry_run_no_upload(tmp_path: Path) -> None:
    client = Mock()
    client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    path = tmp_path / "latest.csv"
    path.write_text("data", encoding="utf-8")
    artifacts = [RawHHArtifact(path, "latest.csv")]

    sync_raw_hh_artifacts(client, "bucket", artifacts, dry_run=True, overwrite=False)
    client.upload_file.assert_not_called()


def test_sync_raw_hh_artifacts_overwrite_skips_head(tmp_path: Path) -> None:
    client = Mock()

    path = tmp_path / "latest.csv"
    path.write_text("data", encoding="utf-8")
    artifacts = [RawHHArtifact(path, "latest.csv")]

    sync_raw_hh_artifacts(client, "bucket", artifacts, dry_run=False, overwrite=True)
    client.head_object.assert_not_called()
    client.upload_file.assert_called_once_with(str(path), "bucket", "latest.csv")


def test_sync_raw_hh_artifacts_missing_local_file(tmp_path: Path) -> None:
    client = Mock()
    artifacts = [RawHHArtifact(tmp_path / "missing.csv", "missing.csv")]

    with pytest.raises(FileNotFoundError):
        sync_raw_hh_artifacts(client, "bucket", artifacts, dry_run=True, overwrite=False)


def test_build_latest_pointer_uses_run_scoped_artifacts(tmp_path: Path) -> None:
    latest = tmp_path / "latest.csv"
    latest.write_text("vacancy_id,title\n1,One\n", encoding="utf-8")
    state = {
        "last_run_id": "2025-02-10T01-00-00Z",
        "run_date": "2025-02-10",
        "row_count": 1,
        "new_count": 1,
        "removed_count": 0,
        "sha256": "state-sha",
        "dataset_scope": "all_vacancies",
        "salary_only": False,
    }
    artifacts = [
        RawHHArtifact(latest, "runs/2025-02-10T01-00-00Z/latest.csv"),
        RawHHArtifact(latest, "latest.csv"),
    ]

    pointer = build_latest_pointer(state, artifacts)

    assert pointer["run_id"] == "2025-02-10T01-00-00Z"
    assert pointer["state"]["row_count"] == 1
    assert pointer["state"]["dataset_scope"] == "all_vacancies"
    assert pointer["state"]["salary_only"] is False
    assert [artifact["key"] for artifact in pointer["artifacts"]] == ["runs/2025-02-10T01-00-00Z/latest.csv"]
    assert pointer["artifacts"][0]["size_bytes"] == latest.stat().st_size


def test_sync_latest_pointer_uploads_json() -> None:
    client = Mock()
    pointer = {"run_id": "run-1"}

    sync_latest_pointer(client, "bucket", pointer, dry_run=False)

    client.put_object.assert_called_once()
    kwargs = client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "bucket"
    assert kwargs["Key"] == "latest_pointer.json"
    assert kwargs["ContentType"] == "application/json"
