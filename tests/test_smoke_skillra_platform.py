from __future__ import annotations

import pytest

from scripts.smoke_skillra_platform import (
    SmokeFailure,
    _validate_health_contour,
    _validate_requested_contour,
    _validate_search_dataset_contract,
)


def test_validate_search_dataset_contract_accepts_matching_run_ids() -> None:
    _validate_search_dataset_contract(
        {
            "dataset_run_id": "run-20260520",
            "index_dataset_run_id": "run-20260520",
            "warnings": [],
        },
        {"dataset_run_id": "run-20260520"},
        "strict",
    )


def test_validate_search_dataset_contract_rejects_missing_dataset_run_in_strict_mode() -> None:
    with pytest.raises(SmokeFailure, match="missing dataset_run_id"):
        _validate_search_dataset_contract({"results": []}, {}, "strict")


def test_validate_search_dataset_contract_rejects_index_dataset_mismatch() -> None:
    with pytest.raises(SmokeFailure, match="index_dataset_run_id does not match"):
        _validate_search_dataset_contract(
            {
                "dataset_run_id": "run-a",
                "index_dataset_run_id": "run-b",
            },
            {"dataset_run_id": "run-a"},
            "strict",
        )


def test_validate_search_dataset_contract_rejects_status_dataset_mismatch() -> None:
    with pytest.raises(SmokeFailure, match="admin indexer-status dataset_run_id does not match"):
        _validate_search_dataset_contract(
            {
                "dataset_run_id": "run-a",
                "index_dataset_run_id": "run-a",
            },
            {"dataset_run_id": "run-b"},
            "strict",
        )


def test_validate_requested_contour_rejects_staging_smoke_against_prod_url() -> None:
    with pytest.raises(SmokeFailure, match="production public base URL"):
        _validate_requested_contour("https://skillra.ru", "staging")


def test_validate_health_contour_requires_runtime_marker() -> None:
    with pytest.raises(SmokeFailure, match="runtime_env"):
        _validate_health_contour(
            {"status": "ok", "runtime_env": "prod", "public_base_url": "https://skillra.ru"},
            expected_runtime_env="staging",
            expected_public_base_url="https://staging.skillra.ru",
        )


def test_validate_health_contour_accepts_expected_staging_marker() -> None:
    _validate_health_contour(
        {"status": "ok", "runtime_env": "staging", "public_base_url": "https://staging.skillra.ru"},
        expected_runtime_env="staging",
        expected_public_base_url="https://staging.skillra.ru/",
    )
