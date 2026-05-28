from __future__ import annotations

import textwrap

from scripts.env_minio_roles import ROLE_ACCESS_KEYS, apply_updates, plan_minio_role_updates


def test_plan_minio_role_updates_splits_duplicate_roles_and_adds_backup_secret() -> None:
    updates = plan_minio_role_updates(
        {
            "MINIO_ACCESS_KEY": "skillra",
            "MINIO_SECRET_KEY": "api-secret",
            "S3_ACCESS_KEY_ID": "skillra",
            "S3_SECRET_ACCESS_KEY": "pipeline-secret",
            "S3_BACKUP_ACCESS_KEY_ID": "skillra-backup",
        }
    )

    assert updates["MINIO_ACCESS_KEY"] == "skillra-api"
    assert updates["S3_ACCESS_KEY_ID"] == "skillra-pipeline"
    assert "S3_BACKUP_SECRET_ACCESS_KEY" in updates
    assert "MINIO_SECRET_KEY" not in updates
    assert "S3_SECRET_ACCESS_KEY" not in updates


def test_plan_minio_role_updates_preserves_valid_custom_role_names() -> None:
    updates = plan_minio_role_updates(
        {
            "MINIO_ACCESS_KEY": "custom-api",
            "MINIO_SECRET_KEY": "api-secret",
            "S3_ACCESS_KEY_ID": "custom-pipeline",
            "S3_SECRET_ACCESS_KEY": "pipeline-secret",
            "S3_BACKUP_ACCESS_KEY_ID": "custom-backup",
            "S3_BACKUP_SECRET_ACCESS_KEY": "backup-secret",
        }
    )

    assert updates == {}


def test_apply_updates_updates_existing_keys_and_appends_missing(tmp_path) -> None:
    env_file = tmp_path / ".env.prod"
    env_file.write_text(
        textwrap.dedent(
            """
            MINIO_ACCESS_KEY=old
            S3_ACCESS_KEY_ID=old
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    apply_updates(env_file, {**ROLE_ACCESS_KEYS, "S3_BACKUP_SECRET_ACCESS_KEY": "secret"})

    content = env_file.read_text(encoding="utf-8")
    assert "MINIO_ACCESS_KEY=skillra-api" in content
    assert "S3_ACCESS_KEY_ID=skillra-pipeline" in content
    assert "S3_BACKUP_ACCESS_KEY_ID=skillra-backup" in content
    assert "S3_BACKUP_SECRET_ACCESS_KEY=secret" in content
