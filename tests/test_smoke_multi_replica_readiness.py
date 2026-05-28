from __future__ import annotations

import pytest

from scripts.smoke_multi_replica_readiness import (
    ReadinessSmokeFailure,
    ReadyResult,
    extract_dataset_run_id,
    normalize_ready_url,
    parse_ready_urls,
    validate_ready_results,
)


def _result(
    url: str,
    *,
    status_code: int = 200,
    status: str = "ok",
    dataset_run_id: str | None = "run-20260520",
    data_consistency: str | None = "ok",
) -> ReadyResult:
    payload = {
        "status": status,
        "dataset_run_id": dataset_run_id,
        "data_consistency": data_consistency,
    }
    return ReadyResult(
        url=url,
        status_code=status_code,
        payload=payload,
        dataset_run_id=dataset_run_id,
        status=status,
        data_consistency=data_consistency,
    )


def test_normalize_ready_url_accepts_base_or_ready_endpoint() -> None:
    assert normalize_ready_url("http://api-1:8000") == "http://api-1:8000/v1/ready"
    assert normalize_ready_url("https://skillra.ru/v1/ready") == "https://skillra.ru/v1/ready"


def test_parse_ready_urls_accepts_repeated_and_comma_separated_values() -> None:
    urls = parse_ready_urls(
        [
            "http://api-1:8000, http://api-2:8000/v1/ready",
            "http://api-1:8000/v1/ready",
        ]
    )

    assert urls == ["http://api-1:8000/v1/ready", "http://api-2:8000/v1/ready"]


def test_extract_dataset_run_id_supports_datastore_fallback() -> None:
    assert extract_dataset_run_id({"dataset_run_id": "run-a"}) == "run-a"
    assert extract_dataset_run_id({"datastore": {"run_id": "run-b"}}) == "run-b"


def test_validate_ready_results_accepts_same_confirmed_dataset_run() -> None:
    dataset_run_id = validate_ready_results(
        [
            _result("http://api-1:8000/v1/ready"),
            _result("http://api-2:8000/v1/ready"),
        ]
    )

    assert dataset_run_id == "run-20260520"


def test_validate_ready_results_rejects_single_url_by_default() -> None:
    with pytest.raises(ReadinessSmokeFailure, match="At least two"):
        validate_ready_results([_result("http://api-1:8000/v1/ready")])


def test_validate_ready_results_rejects_dataset_mismatch() -> None:
    with pytest.raises(ReadinessSmokeFailure, match="different dataset_run_id"):
        validate_ready_results(
            [
                _result("http://api-1:8000/v1/ready", dataset_run_id="run-a"),
                _result("http://api-2:8000/v1/ready", dataset_run_id="run-b"),
            ]
        )


def test_validate_ready_results_rejects_unexpected_dataset_run() -> None:
    with pytest.raises(ReadinessSmokeFailure, match="expected"):
        validate_ready_results(
            [
                _result("http://api-1:8000/v1/ready", dataset_run_id="run-a"),
                _result("http://api-2:8000/v1/ready", dataset_run_id="run-a"),
            ],
            expected_run_id="run-b",
        )


def test_validate_ready_results_requires_ok_data_consistency() -> None:
    with pytest.raises(ReadinessSmokeFailure, match="data_consistency"):
        validate_ready_results(
            [
                _result("http://api-1:8000/v1/ready", data_consistency="unknown"),
                _result("http://api-2:8000/v1/ready", data_consistency="ok"),
            ]
        )


def test_validate_ready_results_rejects_degraded_replica() -> None:
    with pytest.raises(ReadinessSmokeFailure, match="HTTP 503"):
        validate_ready_results(
            [
                _result("http://api-1:8000/v1/ready"),
                _result("http://api-2:8000/v1/ready", status_code=503, status="degraded"),
            ]
        )
