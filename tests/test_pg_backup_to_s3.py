from datetime import datetime, timezone
from typing import Any

import pytest

from scripts import pg_backup_to_s3
from scripts.pg_backup_to_s3 import backup_s3_env, rotate_backups, write_backup_metrics


def test_backup_s3_env_prefers_backup_scoped_credentials() -> None:
    env = {
        "S3_ENDPOINT_URL": "http://localhost:9000",
        "S3_REGION": "us-east-1",
        "S3_ACCESS_KEY_ID": "pipeline",
        "S3_SECRET_ACCESS_KEY": "pipeline-secret",
        "S3_BACKUP_ACCESS_KEY_ID": "backup",
        "S3_BACKUP_SECRET_ACCESS_KEY": "backup-secret",
    }

    resolved = backup_s3_env(env)

    assert resolved["S3_ACCESS_KEY_ID"] == "backup"
    assert resolved["S3_SECRET_ACCESS_KEY"] == "backup-secret"


def test_backup_s3_env_falls_back_to_default_s3_credentials() -> None:
    env = {
        "S3_ENDPOINT_URL": "http://localhost:9000",
        "S3_REGION": "us-east-1",
        "S3_ACCESS_KEY_ID": "pipeline",
        "S3_SECRET_ACCESS_KEY": "pipeline-secret",
    }

    resolved = backup_s3_env(env)

    assert resolved["S3_ACCESS_KEY_ID"] == "pipeline"
    assert resolved["S3_SECRET_ACCESS_KEY"] == "pipeline-secret"


def test_backup_s3_env_rejects_partial_backup_credentials() -> None:
    with pytest.raises(SystemExit, match="Set both S3_BACKUP_ACCESS_KEY_ID"):
        backup_s3_env({"S3_BACKUP_ACCESS_KEY_ID": "backup"})


def test_write_backup_metrics_uses_textfile_format(tmp_path) -> None:  # type: ignore[no-untyped-def]
    metrics_file = tmp_path / "metrics" / "skillra_pg_backup.prom"

    write_backup_metrics(
        metrics_file,
        timestamp=datetime(2026, 5, 19, 15, 0, 0, tzinfo=timezone.utc),
        dump_size_bytes=12345,
        retention_deleted=2,
    )

    text = metrics_file.read_text(encoding="utf-8")
    assert "skillra_pg_backup_last_success_timestamp_seconds 1779202800" in text
    assert "skillra_pg_backup_last_size_bytes 12345" in text
    assert "skillra_pg_backup_last_retention_deleted_objects 2" in text
    assert not (metrics_file.parent / "skillra_pg_backup.prom.tmp").exists()


class _FakePaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs == {"Bucket": "backups", "Prefix": "postgres"}
        return self.pages


class _FakeS3Client:
    def __init__(self) -> None:
        self.deleted: list[dict[str, str]] = []

    def get_paginator(self, name: str) -> _FakePaginator:
        assert name == "list_objects_v2"
        return _FakePaginator(
            [
                {
                    "Contents": [
                        {
                            "Key": "postgres/old.dump",
                            "LastModified": datetime(2026, 5, 1, tzinfo=timezone.utc),
                        },
                        {
                            "Key": "postgres/new.dump",
                            "LastModified": datetime(2026, 5, 28, tzinfo=timezone.utc),
                        },
                    ]
                }
            ]
        )

    def delete_object(self, **kwargs: str) -> None:
        self.deleted.append(kwargs)


def test_rotate_backups_deletes_old_objects_individually(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeS3Client()
    monkeypatch.setattr(pg_backup_to_s3, "create_s3_client", lambda env: client)
    monkeypatch.setattr(pg_backup_to_s3, "backup_s3_env", lambda env=None: {})

    deleted = rotate_backups("backups", "postgres", 7, datetime(2026, 5, 28, tzinfo=timezone.utc))

    assert deleted == 1
    assert client.deleted == [{"Bucket": "backups", "Key": "postgres/old.dump"}]
