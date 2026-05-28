from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.s3_restore as s3_restore
from scripts.s3_restore import calculate_raw_latest_keys, restore_processed_latest, restore_raw_latest


def test_calculate_raw_latest_keys_uses_parquet_fallback() -> None:
    keys = calculate_raw_latest_keys(
        {
            "last_run_id": "2026-05-19T14-10-25Z",
            "run_date": "2026-05-19",
            "snapshot_path": "snapshots/snapshot.csv",
            "delta_path": "deltas/delta.csv",
        }
    )

    assert [key for key in keys] == [
        "state.json",
        "manifest.jsonl",
        "latest.csv",
        "snapshots/snapshot.csv",
        "deltas/delta.csv",
        "snapshots_parquet/date=2026-05-19/snapshot_2026-05-19T14-10-25Z.parquet",
    ]


def test_restore_processed_latest_uses_pointer_latest_and_run_keys(tmp_path: Path, monkeypatch) -> None:
    events: list[tuple[str, str, str]] = []

    def fake_download_bytes(_client, bucket: str, key: str) -> bytes:
        assert bucket == "processed"
        assert key == "latest_pointer.json"
        return b'{"run_id":"20260519T161849Z"}'

    def fake_list_s3_keys(_client, bucket: str, prefix: str = "") -> list[str]:
        assert bucket == "processed"
        if prefix == "latest/":
            return ["latest/dataset_meta.json", "latest/hh_features.parquet"]
        if prefix == "runs/20260519T161849Z/":
            return ["runs/20260519T161849Z/dataset_meta.json"]
        raise AssertionError(f"unexpected prefix: {prefix}")

    def fake_write_bytes(destination: Path, payload: bytes, *, overwrite: bool, dry_run: bool) -> None:
        events.append(("write", destination.relative_to(tmp_path).as_posix(), payload.decode("utf-8")))
        assert overwrite is True
        assert dry_run is False

    def fake_download_key(
        _client,
        bucket: str,
        key: str,
        destination: Path,
        *,
        overwrite: bool,
        dry_run: bool,
    ) -> None:
        assert bucket == "processed"
        assert overwrite is True
        assert dry_run is False
        events.append(("download", key, destination.relative_to(tmp_path).as_posix()))

    monkeypatch.setattr(s3_restore, "download_bytes", fake_download_bytes)
    monkeypatch.setattr(s3_restore, "list_s3_keys", fake_list_s3_keys)
    monkeypatch.setattr(s3_restore, "write_bytes", fake_write_bytes)
    monkeypatch.setattr(s3_restore, "download_key", fake_download_key)

    restore_processed_latest(
        object(),
        "processed",
        tmp_path,
        overwrite=True,
        dry_run=False,
    )

    assert events == [
        ("write", "latest_pointer.json", '{"run_id":"20260519T161849Z"}'),
        ("download", "latest/dataset_meta.json", "latest/dataset_meta.json"),
        ("download", "latest/hh_features.parquet", "latest/hh_features.parquet"),
        (
            "download",
            "runs/20260519T161849Z/dataset_meta.json",
            "runs/20260519T161849Z/dataset_meta.json",
        ),
    ]


def test_restore_raw_latest_uses_pointer_run_artifacts_and_verifies_checksum(tmp_path: Path, monkeypatch) -> None:
    latest_payload = b"vacancy_id,title\n1,One\n"
    state_payload = b'{"last_run_id":"run-1"}'
    payload_by_key = {
        "runs/run-1/latest.csv": latest_payload,
        "runs/run-1/state.json": state_payload,
    }
    pointer = {
        "run_id": "run-1",
        "artifacts": [
            {
                "key": key,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
            for key, payload in payload_by_key.items()
        ],
    }

    def fake_download_bytes(_client, bucket: str, key: str) -> bytes:
        assert bucket == "raw"
        if key == "latest_pointer.json":
            return json.dumps(pointer).encode("utf-8")
        return payload_by_key[key]

    monkeypatch.setattr(s3_restore, "download_bytes", fake_download_bytes)

    restore_raw_latest(object(), "raw", tmp_path, overwrite=True, dry_run=False)

    assert (tmp_path / "latest_pointer.json").exists()
    assert (tmp_path / "latest.csv").read_bytes() == latest_payload
    assert (tmp_path / "state.json").read_bytes() == state_payload
