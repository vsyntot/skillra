from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from scripts import smoke_data_product_release as smoke


def test_validate_health_requires_active_published_dataset() -> None:
    dataset_run_id = "run-1"
    health = {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "meilisearch": "ok",
        "datastore_status": "ok",
        "data_consistency": "ok",
        "runtime_env": "staging",
        "public_base_url": "https://staging.skillra.ru",
        "dataset_run_id": dataset_run_id,
        "data_run": {"active": {"run_id": dataset_run_id, "state": "published"}},
        "search_publish": {"status": "ok", "dataset_run_id": dataset_run_id, "indexed": 10},
    }

    assert (
        smoke._validate_health(
            health,
            expected_runtime_env="staging",
            expected_public_base_url="https://staging.skillra.ru/",
        )
        == dataset_run_id
    )


def test_validate_health_rejects_runtime_env_mismatch() -> None:
    health = {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "meilisearch": "ok",
        "datastore_status": "ok",
        "data_consistency": "ok",
        "runtime_env": "prod",
        "dataset_run_id": "run-1",
        "data_run": {"active": {"run_id": "run-1", "state": "published"}},
        "search_publish": {"status": "ok", "dataset_run_id": "run-1", "indexed": 10},
    }

    with pytest.raises(smoke.DataProductSmokeFailure, match="runtime_env"):
        smoke._validate_health(health, expected_runtime_env="staging")


def test_validate_health_rejects_stale_search_publish() -> None:
    health = {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "meilisearch": "ok",
        "datastore_status": "ok",
        "data_consistency": "ok",
        "dataset_run_id": "run-1",
        "data_run": {"active": {"run_id": "run-1", "state": "published"}},
        "search_publish": {"status": "ok", "dataset_run_id": "run-0", "indexed": 10},
    }

    with pytest.raises(smoke.DataProductSmokeFailure, match="search_publish dataset_run_id"):
        smoke._validate_health(health)


def test_validate_health_rejects_unexpected_run_id() -> None:
    health = {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "meilisearch": "ok",
        "datastore_status": "ok",
        "data_consistency": "ok",
        "dataset_run_id": "run-1",
        "data_run": {"active": {"run_id": "run-1", "state": "published"}},
        "search_publish": {"status": "ok", "dataset_run_id": "run-1", "indexed": 10},
    }

    with pytest.raises(smoke.DataProductSmokeFailure, match="expected run-2"):
        smoke._validate_health(health, expected_run_id="run-2")


def test_validate_search_rejects_result_dataset_mismatch() -> None:
    payload = {
        "dataset_run_id": "run-1",
        "index_dataset_run_id": "run-1",
        "results": [{"dataset_run_id": "run-2"}],
        "warnings": [],
    }

    with pytest.raises(smoke.DataProductSmokeFailure, match="search result dataset_run_id mismatch"):
        smoke._validate_search(payload, "run-1")


def test_validate_trend_blocks_non_trend_ready_dataset() -> None:
    payload = {"claim_status": "blocked", "data": [], "warnings": ["not trend ready"]}

    assert smoke._validate_trend(payload, expected_ready=False, name="salary")["claim_status"] == "blocked"


def test_validate_trend_rejects_data_when_blocked() -> None:
    payload = {"claim_status": "blocked", "data": [{"week": "2026-W20"}]}

    with pytest.raises(smoke.DataProductSmokeFailure, match="must return empty data"):
        smoke._validate_trend(payload, expected_ready=False, name="salary")


def test_validate_processed_s3_checks_latest_and_active_pointers(monkeypatch) -> None:
    dataset_run_id = "run-1"
    latest_pointer = {
        "run_id": dataset_run_id,
        "artifacts": [{"key": "runs/run-1/dataset_meta.json", "sha256": "ok", "size_bytes": 1}],
    }
    active_pointer = {"run_id": dataset_run_id, "latest_pointer": {"run_id": dataset_run_id}}
    payload_by_key = {
        "latest_pointer.json": json.dumps(latest_pointer).encode("utf-8"),
        "hh/published/active_dataset.json": json.dumps(active_pointer).encode("utf-8"),
    }

    monkeypatch.setattr(smoke, "create_s3_client", lambda env: Mock())
    monkeypatch.setattr(smoke, "download_bytes", lambda client, bucket, key: payload_by_key[key])
    monkeypatch.setattr(smoke, "validate_processed_pointer", lambda client, bucket, pointer: [])

    result = smoke._validate_processed_s3("processed-bucket", dataset_run_id)

    assert result["latest_pointer_run_id"] == dataset_run_id
    assert result["active_dataset_run_id"] == dataset_run_id
