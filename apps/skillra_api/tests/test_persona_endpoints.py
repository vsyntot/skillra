from __future__ import annotations

import asyncio
import csv
import io
import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.db import Base
from skillra_api.db.models import ShareToken
from skillra_api.main import create_app  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def aclose(self) -> None:
        return None


class FailingRedis:
    async def set(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise ConnectionError("redis down")

    async def get(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise ConnectionError("redis down")

    async def aclose(self) -> None:
        return None


async def _create_schema(app) -> None:
    async with app.state.db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _write_dataset_meta(tmp_path: Path) -> Path:
    dataset_meta_path = tmp_path / "dataset_meta.json"
    dataset_meta_path.write_text(
        json.dumps(
            {
                "run_id": "persona-test-run",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return dataset_meta_path


@pytest.fixture()
def persona_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"
    dataset_meta_path = _write_dataset_meta(tmp_path)

    features_df = pd.DataFrame(
        {
            "primary_role": ["data", "data"],
            "grade_final": ["junior", "junior"],
            "city_tier": ["Moscow", "SPb"],
            "work_mode": ["office", "remote"],
            "salary_mid_rub_capped": [120000, 150000],
            "salary_disclosed": [True, False],
            "is_remote": [False, True],
            "skill_sql": [True, True],
            "skill_python": [True, False],
        }
    )
    features_df.to_parquet(features_path)

    market_view_df = pd.DataFrame(
        {
            "primary_role": ["data"],
            "city_tier": ["Moscow"],
            "grade_final": ["junior"],
            "vacancy_count": [2],
        }
    )
    market_view_df.to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        dataset_meta_path=str(dataset_meta_path),
        api_token=service_token,
        database_url="",
        redis_url="",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.app.state.redis = FakeRedis()
        client.headers.update(auth_headers)
        yield client


@pytest.fixture()
def persona_db_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "hh_features_db.parquet"
    market_view_path = tmp_path / "market_view_db.parquet"
    dataset_meta_path = _write_dataset_meta(tmp_path)

    features_df = pd.DataFrame(
        {
            "primary_role": ["data", "data"],
            "grade_final": ["junior", "junior"],
            "city_tier": ["Moscow", "SPb"],
            "work_mode": ["office", "remote"],
            "salary_mid_rub_capped": [120000, 150000],
            "salary_disclosed": [True, False],
            "is_remote": [False, True],
            "skill_sql": [True, True],
            "skill_python": [True, False],
        }
    )
    features_df.to_parquet(features_path)
    market_view_df = pd.DataFrame(
        {
            "primary_role": ["data"],
            "city_tier": ["Moscow"],
            "grade_final": ["junior"],
            "vacancy_count": [2],
        }
    )
    market_view_df.to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        dataset_meta_path=str(dataset_meta_path),
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'persona_share.db'}",
        redis_url="",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    asyncio.run(_create_schema(app))
    with TestClient(app) as client:
        client.headers.update(auth_headers)
        yield client


def _persona_payload() -> dict[str, object]:
    return {
        "name": "Test Persona",
        "description": "Testing persona analysis",
        "current_skills": ["sql"],
        "target_role": "data",
        "target_grade": "junior",
    }


def test_persona_analyze_returns_json(persona_client: TestClient) -> None:
    response = persona_client.post("/v1/persona/analyze", json=_persona_payload())

    assert response.status_code == 200
    body = response.json()
    assert "market_summary" in body
    assert isinstance(body.get("recommended_skills"), list)
    assert isinstance(body.get("skill_gap"), list)
    assert isinstance(body.get("top_skill_demand"), list)
    assert "skill_resources" in body
    assert body["market_summary"]["vacancy_count"] == 2
    assert body["market_summary"]["sample_size"] == 2
    assert body["market_summary"]["salary_sample_size"] == 1
    assert body["market_summary"]["salary_coverage_share"] == 0.5
    assert body["market_summary"]["confidence"] == "low"
    assert body["dataset_run_id"] == "persona-test-run"
    assert body["market_summary"]["dataset_run_id"] == "persona-test-run"
    assert body["generated_at_utc"]
    assert body["freshness"] in {"fresh", "aging", "stale"}


def test_persona_skill_gap_chart_returns_png(persona_client: TestClient) -> None:
    response = persona_client.post("/v1/persona/skill-gap-chart", json=_persona_payload())

    assert response.status_code == 200
    assert response.headers.get("content-type") == "image/png"
    assert response.content


def test_persona_accepts_canonical_skills(persona_client: TestClient) -> None:
    payload = _persona_payload()
    payload["current_skills"] = ["python"]

    response = persona_client.post("/v1/persona/analyze", json=payload)
    assert response.status_code == 200

    body = response.json()
    assert all(not entry["skill_name"].startswith("skill_") for entry in body["skill_gap"])
    assert all(entry.get("skill_name_raw", "").startswith("skill_") for entry in body["skill_gap"])
    assert all(skill.islower() for skill in body.get("recommended_skills", []))


def test_persona_analyze_matches_schema(persona_client: TestClient) -> None:
    response = persona_client.post("/v1/persona/analyze", json=_persona_payload())

    assert response.status_code == 200
    body = response.json()

    expected_keys = {
        "market_summary",
        "recommended_skills",
        "top_skill_demand",
        "skill_gap",
        "skill_resources",
        "warnings",
        "filters_used",
    }
    assert expected_keys.issubset(body)

    market_summary = body["market_summary"]
    market_fields = {
        "vacancy_count",
        "sample_size",
        "salary_sample_size",
        "salary_coverage_share",
        "confidence",
        "min_market_n",
        "salary_median",
        "salary_q25",
        "salary_q75",
        "remote_share",
        "geo_scope",
        "junior_friendly_share",
        "top_skills",
    }
    assert market_fields.issubset(market_summary)
    assert isinstance(market_summary["vacancy_count"], int)
    assert market_summary["top_skills"] is None or (
        isinstance(market_summary["top_skills"], list)
        and all(isinstance(skill, str) for skill in market_summary["top_skills"])
    )

    assert isinstance(body["recommended_skills"], list)
    assert all(isinstance(skill, str) for skill in body["recommended_skills"])
    assert isinstance(body["skill_resources"], dict)

    assert isinstance(body["top_skill_demand"], list)
    for entry in body["top_skill_demand"]:
        assert {"skill_name", "market_share"}.issubset(entry)
        assert isinstance(entry["skill_name"], str)
        assert isinstance(entry["market_share"], (int, float))

    assert isinstance(body["skill_gap"], list)
    for gap_entry in body["skill_gap"]:
        assert {"skill_name", "market_share", "persona_has", "gap"}.issubset(gap_entry)
        assert isinstance(gap_entry["persona_has"], bool)
        assert isinstance(gap_entry["gap"], bool)

    assert isinstance(body["warnings"], list)
    assert isinstance(body["filters_used"], dict)


def test_export_csv_includes_trust_metadata(persona_client: TestClient) -> None:
    response = persona_client.post("/v1/persona/export-csv", json=_persona_payload())

    assert response.status_code == 200
    assert response.headers.get("x-skillra-dataset-run-id") == "persona-test-run"
    assert response.headers.get("x-skillra-generated-at-utc")
    assert response.headers.get("x-skillra-freshness") in {"fresh", "aging", "stale"}
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
    assert rows
    assert rows[0]["dataset_run_id"] == "persona-test-run"
    assert rows[0]["generated_at_utc"]
    assert rows[0]["freshness"] in {"fresh", "aging", "stale"}
    assert rows[0]["sample_size"] == "2"
    assert rows[0]["confidence"] == "low"
    assert rows[0]["salary_coverage_share"] == "0.5"


# ---------------------------------------------------------------------------
# Sprint-009 TASK-12 / Gap-v8 ST-NEW-05: export-pdf tests
# ---------------------------------------------------------------------------


def test_export_pdf_returns_pdf(persona_client: TestClient) -> None:
    response = persona_client.post("/v1/persona/export-pdf", json=_persona_payload())
    assert response.status_code == 200, f"export-pdf returned unexpected status {response.status_code}: {response.text}"
    assert "application/pdf" in response.headers.get("content-type", "")
    assert response.headers.get("x-skillra-dataset-run-id") == "persona-test-run"
    assert response.headers.get("x-skillra-generated-at-utc")
    assert response.headers.get("x-skillra-freshness") in {"fresh", "aging", "stale"}
    assert response.headers.get("x-skillra-sample-size") == "2"
    assert response.headers.get("x-skillra-confidence") == "low"
    assert len(response.content) > 0


def test_export_pdf_invalid_role_returns_4xx(persona_client: TestClient) -> None:
    payload = _persona_payload()
    payload["target_role"] = "non_existent_role_xyz"
    response = persona_client.post("/v1/persona/export-pdf", json=payload)
    assert response.status_code in (
        200,
        400,
        422,
    ), f"export-pdf returned unexpected status {response.status_code}: {response.text}"
    if response.status_code == 200:
        assert "application/pdf" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Sprint-009 TASK-13 / Gap-v8 ST-NEW-05: persona/share tests
# ---------------------------------------------------------------------------


def test_create_share_link_returns_token(persona_client: TestClient) -> None:
    """POST /v1/persona/share should return JSON with token and expires_in."""
    response = persona_client.post("/v1/persona/share", json=_persona_payload())
    assert (
        response.status_code == 200
    ), f"share endpoint returned unexpected status {response.status_code}: {response.text}"
    body = response.json()
    assert "token" in body, f"Missing 'token' in response: {body}"
    assert "expires_in" in body, f"Missing 'expires_in' in response: {body}"
    assert isinstance(body["token"], str) and len(body["token"]) > 0
    assert body["expires_in"] == 604800  # 7 days in seconds


def test_get_shared_analysis_is_public(persona_client: TestClient) -> None:
    response = persona_client.post("/v1/persona/share", json=_persona_payload())
    assert response.status_code == 200
    token = response.json()["token"]

    persona_client.headers.clear()
    shared = persona_client.get(f"/v1/persona/share/{token}")

    assert shared.status_code == 200
    body = shared.json()
    assert "market_summary" in body
    assert "skill_gap" in body
    assert body["dataset_run_id"] == "persona-test-run"
    assert body["market_summary"]["dataset_run_id"] == "persona-test-run"
    assert body["generated_at_utc"]


def test_get_shared_analysis_returns_404_for_unknown_token(persona_client: TestClient) -> None:
    """GET /v1/persona/share/{token} should return 404 for unknown token."""
    persona_client.headers.clear()
    response = persona_client.get("/v1/persona/share/totally-unknown-token-xyz123")
    assert (
        response.status_code == 404
    ), f"share/{{token}} returned unexpected status {response.status_code}: {response.text}"


def test_share_works_without_redis(persona_db_client: TestClient) -> None:
    response = persona_db_client.post("/v1/persona/share", json=_persona_payload())

    assert response.status_code == 200
    token = response.json()["token"]

    persona_db_client.headers.clear()
    shared = persona_db_client.get(f"/v1/persona/share/{token}")
    assert shared.status_code == 200
    assert "market_summary" in shared.json()


def test_share_redis_fallback_to_db(persona_db_client: TestClient) -> None:
    persona_db_client.app.state.redis = FailingRedis()

    response = persona_db_client.post("/v1/persona/share", json=_persona_payload())

    assert response.status_code == 200
    token = response.json()["token"]

    persona_db_client.headers.clear()
    shared = persona_db_client.get(f"/v1/persona/share/{token}")
    assert shared.status_code == 200
    assert "skill_gap" in shared.json()


def test_share_token_expiry(persona_db_client: TestClient) -> None:
    async def _insert_expired() -> None:
        async with persona_db_client.app.state.session_maker() as session:
            session.add(
                ShareToken(
                    token="expired-token",
                    payload="{}",
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                )
            )
            await session.commit()

    asyncio.run(_insert_expired())

    persona_db_client.headers.clear()
    response = persona_db_client.get("/v1/persona/share/expired-token")
    assert response.status_code == 404
