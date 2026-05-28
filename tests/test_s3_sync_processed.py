from __future__ import annotations

from pathlib import Path

import boto3
from botocore.stub import ANY, Stubber

import scripts.s3_sync_processed as s3_sync_processed
from scripts.s3_sync_processed import (
    ProcessedArtifact,
    build_lake_artifacts,
    build_latest_artifacts,
    build_latest_pointer,
    build_processed_run_artifacts,
    sync_latest_pointer,
    sync_processed_artifacts,
    validate_processed_pointer,
)


def test_build_processed_run_artifacts_layout(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    run_id = "20250210T010000Z"
    run_dir = processed_dir / "runs" / run_id
    run_dir.mkdir(parents=True)

    expected_files = [
        "dataset_meta.json",
        "hh_clean.parquet",
        "hh_features.parquet",
        "market_view.parquet",
    ]
    for name in expected_files:
        (run_dir / name).write_text("data", encoding="utf-8")

    artifacts = build_processed_run_artifacts(processed_dir, run_id)
    keys = [artifact.key for artifact in artifacts]

    assert keys == [f"runs/{run_id}/{name}" for name in expected_files]


def test_build_latest_artifacts_from_symlink(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    run_id = "20250210T010000Z"
    run_dir = processed_dir / "runs" / run_id
    run_dir.mkdir(parents=True)

    expected_files = [
        "dataset_meta.json",
        "hh_clean.parquet",
        "hh_features.parquet",
        "market_view.parquet",
    ]
    for name in expected_files:
        (run_dir / name).write_text("data", encoding="utf-8")

    latest_dir = processed_dir / "latest"
    latest_dir.symlink_to(run_dir, target_is_directory=True)

    artifacts = build_latest_artifacts(processed_dir)
    keys = [artifact.key for artifact in artifacts]

    assert keys == [f"latest/{name}" for name in expected_files]
    assert all(artifact.overwrite_existing for artifact in artifacts)


def test_build_lake_artifacts_layout(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    run_id = "20250210T010000Z"
    run_dir = processed_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    for name in [
        "dataset_meta.json",
        "hh_clean.parquet",
        "hh_features.parquet",
        "market_view.parquet",
        "quality_report.json",
        "run_manifest.json",
    ]:
        (run_dir / name).write_text("data", encoding="utf-8")

    artifacts = build_lake_artifacts(processed_dir, run_id)
    keys = [artifact.key for artifact in artifacts]

    assert keys == [
        f"hh/bronze/run={run_id}/hh_clean.parquet",
        f"hh/silver/run={run_id}/hh_features.parquet",
        f"hh/gold/run={run_id}/market_view.parquet",
        f"hh/manifests/run={run_id}/dataset_meta.json",
        f"hh/manifests/run={run_id}/quality_report.json",
        f"hh/manifests/run={run_id}/manifest.json",
    ]


def test_sync_processed_artifacts_overwrites_latest_but_skips_existing_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_file = tmp_path / "run.parquet"
    latest_file = tmp_path / "latest.parquet"
    run_file.write_text("old", encoding="utf-8")
    latest_file.write_text("new", encoding="utf-8")

    checked_keys: list[str] = []
    uploaded_keys: list[str] = []

    def fake_s3_object_exists(_client, _bucket: str, key: str) -> bool:
        checked_keys.append(key)
        return True

    def fake_put_file(_client, _bucket: str, key: str, _local_path: Path) -> None:
        uploaded_keys.append(key)

    monkeypatch.setattr(s3_sync_processed, "s3_object_exists", fake_s3_object_exists)
    monkeypatch.setattr(s3_sync_processed, "put_file", fake_put_file)

    sync_processed_artifacts(
        object(),
        "bucket",
        [
            ProcessedArtifact(run_file, "runs/20250210T010000Z/hh_features.parquet"),
            ProcessedArtifact(latest_file, "latest/hh_features.parquet", overwrite_existing=True),
        ],
        dry_run=False,
        overwrite=False,
    )

    assert checked_keys == ["runs/20250210T010000Z/hh_features.parquet"]
    assert uploaded_keys == ["latest/hh_features.parquet"]


def test_sync_latest_pointer_uploads_payload() -> None:
    client = boto3.client("s3", region_name="us-east-1")
    stubber = Stubber(client)
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "bucket", "Key": "latest_pointer.json", "Body": ANY, "ContentType": "application/json"},
    )
    stubber.activate()

    pointer = build_latest_pointer({"run_id": "20250210T010000Z", "generated_at_utc": "2025-02-10T01:00:00Z"})
    sync_latest_pointer(client, "bucket", pointer, dry_run=False)

    stubber.deactivate()


def test_build_latest_pointer_includes_artifact_manifest(tmp_path: Path) -> None:
    artifact_path = tmp_path / "hh_features.parquet"
    artifact_path.write_text("processed", encoding="utf-8")

    pointer = build_latest_pointer(
        {"run_id": "20250210T010000Z", "generated_at_utc": "2025-02-10T01:00:00Z"},
        [ProcessedArtifact(artifact_path, "runs/20250210T010000Z/hh_features.parquet")],
    )

    assert pointer["run_id"] == "20250210T010000Z"
    assert pointer["artifacts"][0]["key"] == "runs/20250210T010000Z/hh_features.parquet"
    assert pointer["artifacts"][0]["size_bytes"] == artifact_path.stat().st_size
    assert pointer["artifacts"][0]["sha256"]


def test_validate_processed_pointer_detects_checksum_mismatch(monkeypatch) -> None:
    payload_by_key = {"runs/run-1/hh_features.parquet": b"actual"}

    def fake_download_bytes(_client, _bucket: str, key: str) -> bytes:
        return payload_by_key[key]

    monkeypatch.setattr(s3_sync_processed, "download_bytes", fake_download_bytes)

    failures = validate_processed_pointer(
        object(),
        "bucket",
        {
            "run_id": "run-1",
            "artifacts": [
                {
                    "key": "runs/run-1/hh_features.parquet",
                    "sha256": "bad",
                    "size_bytes": len(b"actual"),
                }
            ],
        },
    )

    assert any("sha256 mismatch" in failure for failure in failures)
