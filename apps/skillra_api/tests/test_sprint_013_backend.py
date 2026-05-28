from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings
from skillra_api.db import Base
from skillra_api.main import create_app
from skillra_api.services.circuit_breaker import with_retry


class FakeStorageService:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def upload_resume(self, telegram_user_id: int, file_bytes: bytes, content_type: str) -> str:
        key = f"resumes/{telegram_user_id}/resume-{len(self.uploaded) + 1}.pdf"
        self.uploaded[key] = file_bytes
        return key

    async def get_resume_presigned_url(self, s3_key: str, ttl: int = 3600) -> str:
        return f"https://storage.local/{s3_key}?ttl={ttl}"

    async def delete_resume(self, s3_key: str) -> None:
        self.deleted.append(s3_key)


async def _prepare_database(app) -> None:
    async with app.state.db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture()
def sprint13_client(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
    auth_headers: dict[str, str],
) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"
    snapshots_dir = tmp_path / "market_snapshots"
    dataset_meta_path = tmp_path / "dataset_meta.json"
    database_path = tmp_path / "sprint13.db"

    features_df = pd.DataFrame(
        {
            "primary_role": ["data", "data", "data", "data"],
            "grade_final": ["junior", "middle", "middle", "senior"],
            "city_tier": ["Moscow", "Moscow", "Moscow", "Moscow"],
            "work_mode": ["remote", "remote", "remote", "remote"],
            "domain": ["analytics", "analytics", "analytics", "analytics"],
            "salary_mid_rub_capped": [100.0, 150.0, 170.0, 220.0],
            "skill_python": [True, True, True, True],
            "skill_sql": [True, True, True, True],
            "skill_airflow": [False, True, True, True],
            "skill_leadership": [False, False, False, True],
        }
    )
    features_df.to_parquet(features_path)
    features_df.to_parquet(market_view_path)

    snapshots_dir.mkdir()
    pd.DataFrame(
        [
            {
                "week_start": date(2026, 5, 4),
                "role": "data",
                "grade": "junior",
                "city_tier": "Moscow",
                "work_mode": "remote",
                "domain": "analytics",
                "vacancy_count": 4,
                "salary_p25": 90.0,
                "salary_p50": 100.0,
                "salary_p75": 110.0,
                "skill_top10": ["python", "sql"],
            },
            {
                "week_start": date(2026, 5, 11),
                "role": "data",
                "grade": "junior",
                "city_tier": "Moscow",
                "work_mode": "remote",
                "domain": "analytics",
                "vacancy_count": 6,
                "salary_p25": 100.0,
                "salary_p50": 120.0,
                "salary_p75": 130.0,
                "skill_top10": ["python", "sql"],
            },
        ]
    ).to_parquet(snapshots_dir / "2026-W18.parquet")
    dataset_meta_path.write_text(
        json.dumps(
            {
                "run_id": "test-historical-run",
                "source_kind": "historical_publication_facts",
                "dataset_semantic_type": "historical_publication_facts",
                "date_semantics_status": "passed",
                "trend_ready_gate": {
                    "gate_version": "2026-05-27.v1",
                    "status": "passed",
                    "eligible": True,
                    "failed_criteria": [],
                },
                "product_eligibility": {
                    "trends": {
                        "eligible": True,
                        "gate_version": "2026-05-27.v1",
                        "reason": "trend-ready gates passed",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        market_snapshots_path=str(snapshots_dir),
        dataset_meta_path=str(dataset_meta_path),
        api_token=service_token,
        admin_token=admin_token,
        database_url=f"sqlite+aiosqlite:///{database_path}",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    app.state.storage_service = FakeStorageService()
    with TestClient(app) as client:
        client.portal.call(_prepare_database, app)
        client.headers.update(auth_headers)
        yield client


def test_salary_trends_endpoint(sprint13_client: TestClient) -> None:
    response = sprint13_client.get("/v1/market/trends/salary", params={"role": "data", "grade": "junior"})

    assert response.status_code == 200
    body = response.json()
    assert body["metric"] == "p50"
    assert [point["value"] for point in body["data"]] == [100.0, 120.0]
    assert body["claim_status"] == "ready"
    assert body["source_kind"] == "historical_publication_facts"


def test_skill_demand_trends_endpoint(sprint13_client: TestClient) -> None:
    response = sprint13_client.get("/v1/market/trends/skill-demand", params={"skill": "python", "role": "data"})

    assert response.status_code == 200
    assert response.json()["data"][-1]["value"] == 6.0


def test_trends_block_when_dataset_is_not_trend_eligible(sprint13_client: TestClient) -> None:
    sprint13_client.app.state.datastore._dataset_meta = {  # noqa: SLF001
        "run_id": "current-snapshot-run",
        "source_kind": "current_market_snapshot",
        "dataset_semantic_type": "current_market_snapshot",
        "date_semantics_status": "failed",
        "product_eligibility": {"trends": {"eligible": False, "reason": "historical trend-readiness gates not passed"}},
    }

    response = sprint13_client.get("/v1/market/trends/salary", params={"role": "data", "grade": "junior"})

    assert response.status_code == 200
    body = response.json()
    assert body["claim_status"] == "blocked"
    assert body["data"] == []
    assert body["source_kind"] == "current_market_snapshot"
    assert "Историческая динамика сейчас заблокирована" in body["warnings"][0]


def test_career_trajectory_and_graph_endpoints(sprint13_client: TestClient) -> None:
    trajectory = sprint13_client.get(
        "/v1/persona/career-trajectory",
        params={"role": "data", "grade": "junior", "skills": "python,sql"},
    )
    assert trajectory.status_code == 200
    assert trajectory.json()["next_grade"] == "middle"
    assert "airflow" in trajectory.json()["skills_to_add"]

    graph = sprint13_client.get("/v1/market/career-graph", params={"role": "data"})
    assert graph.status_code == 200
    assert graph.json()["transitions"][0]["to_grade"] == "middle"


def test_resume_upload_status_presigned_and_delete(sprint13_client: TestClient) -> None:
    upload = sprint13_client.post(
        "/v1/users/777/resume",
        params={"filename": "cv.pdf"},
        content=b"Python and SQL resume",
        headers={"Content-Type": "application/pdf", **sprint13_client.headers},
    )
    assert upload.status_code == 200
    assert upload.json()["extracted_skills"] == ["python", "sql"]

    status = sprint13_client.get("/v1/users/777/resume")
    assert status.status_code == 200
    assert status.json()["uploaded"] is True
    assert status.json()["presigned_url"].startswith("https://storage.local/")

    presigned = sprint13_client.get("/v1/users/777/resume/presigned-url", params={"ttl": 3600})
    assert presigned.status_code == 200
    assert presigned.json()["ttl"] == 3600

    deleted = sprint13_client.delete("/v1/users/777/resume")
    assert deleted.status_code == 204
    assert sprint13_client.get("/v1/users/777/resume").json()["uploaded"] is False


def test_resume_reupload_deletes_previous_object(sprint13_client: TestClient) -> None:
    first = sprint13_client.post(
        "/v1/users/778/resume",
        params={"filename": "cv.pdf"},
        content=b"Python resume",
        headers={"Content-Type": "application/pdf", **sprint13_client.headers},
    )
    second = sprint13_client.post(
        "/v1/users/778/resume",
        params={"filename": "cv.pdf"},
        content=b"SQL resume",
        headers={"Content-Type": "application/pdf", **sprint13_client.headers},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["s3_key"] != second.json()["s3_key"]
    storage = sprint13_client.app.state.storage_service
    assert storage.deleted == [first.json()["s3_key"]]


def test_retry_decorator_retries_on_transient_error() -> None:
    calls = 0

    @with_retry(RuntimeError, max_attempts=3, wait_min=0, wait_max=0)
    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary")
        return "ok"

    assert asyncio.get_event_loop().run_until_complete(flaky()) == "ok"
    assert calls == 3
