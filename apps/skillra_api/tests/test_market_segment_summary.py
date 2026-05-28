import json
from collections.abc import Generator
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.main import create_app  # noqa: E402


@pytest.fixture()
def segment_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"

    features_df = pd.DataFrame(
        {
            "primary_role": [
                "data",
                "data",
                "data",
                "data",
                "data",
                "data",
                "data",
                "ml",
            ],
            "grade_final": [
                "senior",
                "senior",
                "senior",
                "senior",
                "senior",
                "senior",
                "junior",
                "senior",
            ],
            "city_tier": [
                "Moscow",
                "Moscow",
                "Moscow",
                "Moscow",
                "Moscow",
                "SPb",
                "Moscow",
                "SPb",
            ],
            "country": ["Russia"] * 8,
            "region": [
                "Moscow",
                "Moscow",
                "Moscow",
                "Moscow",
                "Moscow",
                "Saint Petersburg",
                "Moscow",
                "Saint Petersburg",
            ],
            "city_normalized": [
                "Moscow",
                "Moscow",
                "Moscow",
                "Moscow",
                "Moscow",
                "Saint Petersburg",
                "Moscow",
                "Saint Petersburg",
            ],
            "work_mode": [
                "office",
                "remote",
                "remote",
                "remote",
                "remote",
                "remote",
                "remote",
                "remote",
            ],
            "geo_scope": ["local", "remote", "remote", "remote", "remote", "remote", "remote", "remote"],
            "domain": [
                "analytics",
                "analytics",
                "analytics",
                "analytics",
                "analytics",
                "analytics",
                "analytics",
                "platform",
            ],
            "salary_mid_rub_capped": [120, 150, 180, 200, 220, 240, 90, 210],
            "is_junior_friendly": [False, True, False, False, False, True, True, False],
            "tech_stack_size": [6, 5, 6, 7, 8, 6, 4, 5],
            "is_remote": [False, True, True, True, True, True, True, True],
        }
    )
    features_df.to_parquet(features_path)

    market_view_df = pd.DataFrame(
        {
            "primary_role": ["data", "data", "data", "ml"],
            "city_tier": ["Moscow", "SPb", "Moscow", "SPb"],
            "country": ["Russia", "Russia", "Russia", "Russia"],
            "region": ["Moscow", "Saint Petersburg", "Moscow", "Saint Petersburg"],
            "city_normalized": ["Moscow", "Saint Petersburg", "Moscow", "Saint Petersburg"],
            "geo_scope": ["mixed", "remote", "remote", "remote"],
            "grade_final": ["senior", "senior", "junior", "senior"],
            "domain": ["analytics", "analytics", "analytics", "platform"],
            "vacancy_count": [5, 7, 3, 2],
            "vacancy_count_total": [5, 7, 3, 2],
            "vacancy_count_salary": [4, 7, 2, 2],
            "sample_size": [5, 7, 3, 2],
            "salary_sample_size": [4, 7, 2, 2],
            "salary_coverage_share": [0.8, 1.0, 0.666667, 1.0],
            "confidence": ["low", "low", "low", "low"],
            "salary_median": [120, 130, 70, 110],
            "salary_q25": [110, 120, 60, 100],
            "salary_q75": [130, 140, 80, 120],
            "junior_friendly_share": [0.1, 0.15, 0.3, 0.05],
            "remote_share": [0.6, 0.8, 0.7, 0.5],
            "median_tech_stack_size": [6, 7, 4, 5],
            "top_skills": [
                ["Python", "SQL", "Machine Learning"],
                ["Python", "SQL", "Airflow"],
                ["Python", "SQL"],
                ["Python", "Spark"],
            ],
        }
    )
    market_view_df.to_parquet(market_view_path)
    dataset_meta_path = tmp_path / "dataset_meta.json"
    dataset_meta_path.write_text(
        json.dumps(
            {
                "run_id": "segment-test-run",
                "generated_at_utc": "2026-05-27T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        dataset_meta_path=str(dataset_meta_path),
        api_token=service_token,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update(auth_headers)
        yield client


def test_segment_summary_returns_metrics(segment_client: TestClient) -> None:
    response = segment_client.post(
        "/v1/market/segment-summary",
        json={
            "role": "data",
            "grade": "senior",
            "city_tier": "Moscow",
            "domain": "analytics",
        },
    )

    assert response.status_code == 200
    body = response.json()
    expected = {
        "vacancy_count": 5,
        "sample_size": 5,
        "salary_sample_size": 4,
        "salary_coverage_share": 0.8,
        "confidence": "low",
        "salary_median": 120.0,
        "salary_q25": 110.0,
        "salary_q75": 130.0,
        "junior_friendly_share": 0.1,
        "remote_share": 0.6,
        "geo_scope": "mixed",
        "median_tech_stack_size": 6.0,
        "top_skills": ["Python", "SQL", "Machine Learning"],
        "warnings": ["Segment confidence is low; salary and demand metrics may be unstable."],
    }
    for key, value in expected.items():
        assert body[key] == value
    assert body["dataset_run_id"] == "segment-test-run"
    assert body["generated_at_utc"]
    assert body["freshness"] in {"fresh", "aging", "stale"}


def test_segment_summary_handles_empty_segment(segment_client: TestClient) -> None:
    response = segment_client.post(
        "/v1/market/segment-summary",
        json={"role": "data", "grade": "lead", "domain": "analytics"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["vacancy_count"] == 0
    assert body["salary_median"] is None
    assert body["top_skills"] is None
    # TASK-03 (C-GAP-04): unknown grade value triggers a validation warning
    assert any("lead" in w for w in body["warnings"]), f"Expected grade warning, got: {body['warnings']}"
    # Empty segment warning may also be present
    all_warnings_text = " ".join(body["warnings"])
    assert "lead" in all_warnings_text or "Segment is empty" in all_warnings_text


def test_segment_summary_filters_by_work_mode(segment_client: TestClient) -> None:
    response = segment_client.post(
        "/v1/market/segment-summary",
        json={
            "role": "data",
            "grade": "senior",
            "work_mode": "remote",
            "domain": "analytics",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["vacancy_count"] == 5
    assert body["sample_size"] == 5
    assert body["salary_sample_size"] == 5
    assert body["salary_coverage_share"] == 1.0
    assert body["confidence"] == "low"
    assert body["salary_median"] == 200.0
    assert body["salary_q25"] == 180.0
    assert body["salary_q75"] == 220.0
    assert body["remote_share"] == 1.0
    assert body["geo_scope"] == "remote"
    assert body["junior_friendly_share"] == pytest.approx(0.4)
    assert body["median_tech_stack_size"] == 6.0
    assert body["warnings"] == ["Segment confidence is low; salary and demand metrics may be unstable."]


def test_segment_summary_filters_by_normalized_geography(segment_client: TestClient) -> None:
    response = segment_client.post(
        "/v1/market/segment-summary",
        json={
            "role": "data",
            "grade": "senior",
            "country": "Russia",
            "city": "Saint Petersburg",
            "geo_scope": "remote",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["vacancy_count"] == 7
    assert body["geo_scope"] == "remote"


def test_segment_summary_matches_schema(segment_client: TestClient) -> None:
    response = segment_client.post(
        "/v1/market/segment-summary",
        json={"role": "data", "grade": "senior", "city_tier": "Moscow"},
    )

    assert response.status_code == 200
    body = response.json()

    expected_keys = {
        "vacancy_count",
        "sample_size",
        "salary_sample_size",
        "salary_coverage_share",
        "confidence",
        "salary_median",
        "salary_q25",
        "salary_q75",
        "junior_friendly_share",
        "remote_share",
        "geo_scope",
        "median_tech_stack_size",
        "top_skills",
        "warnings",
    }
    assert expected_keys.issubset(body)
    assert isinstance(body["vacancy_count"], int)
    assert body["sample_size"] is None or isinstance(body["sample_size"], int)
    assert body["salary_sample_size"] is None or isinstance(body["salary_sample_size"], int)
    assert body["confidence"] is None or body["confidence"] in {"low", "medium", "high"}
    assert isinstance(body["warnings"], list)
    assert body["top_skills"] is None or (
        isinstance(body["top_skills"], list) and all(isinstance(skill, str) for skill in body["top_skills"])
    )
    numeric_fields = [
        "salary_median",
        "salary_q25",
        "salary_q75",
        "salary_coverage_share",
        "junior_friendly_share",
        "remote_share",
        "median_tech_stack_size",
    ]
    for field in numeric_fields:
        assert body[field] is None or isinstance(body[field], (int, float))


def test_segment_summary_rate_limit(segment_client: TestClient) -> None:
    pytest.importorskip("slowapi")

    payload = {"role": "data", "grade": "senior", "city_tier": "Moscow"}
    last_response = None
    for _ in range(61):
        last_response = segment_client.post("/v1/market/segment-summary", json=payload)

    assert last_response is not None
    assert last_response.status_code == 429
