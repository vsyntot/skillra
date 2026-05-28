from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from skillra_api.config import Settings
from skillra_api.constants import ADMIN_TOKEN_HEADER, SERVICE_TOKEN_HEADER
from skillra_api.db import Base
from skillra_api.main import create_app
from skillra_api.services.data_runs import upsert_data_run_state

from skillra_pda.ingest.source_registry import build_source_capability_ref


async def _create_schema(app) -> None:
    async with app.state.db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _app(db_url: str, service_token: str, admin_token: str):
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        admin_token=admin_token,
        database_url=db_url,
        redis_url="",
        meilisearch_url="",
        data_watch_interval=0,
    )
    return create_app(settings)


def _headers(service_token: str, admin_token: str) -> dict[str, str]:
    return {SERVICE_TOKEN_HEADER: service_token, ADMIN_TOKEN_HEADER: admin_token}


def test_data_run_state_lifecycle(tmp_path: Path, service_token: str, admin_token: str) -> None:
    app = _app(f"sqlite+aiosqlite:///{tmp_path / 'data_runs.db'}", service_token, admin_token)
    asyncio.run(_create_schema(app))

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/data-runs/run-1/state",
            headers=_headers(service_token, admin_token),
            json={"state": "collecting", "source": "test"},
        )
        assert response.status_code == 200
        assert response.json()["state"] == "collecting"

        response = client.post(
            "/v1/admin/data-runs/run-1/state",
            headers=_headers(service_token, admin_token),
            json={"state": "processed_validated", "processed_rows": 42},
        )
        assert response.status_code == 200

        response = client.post(
            "/v1/admin/data-runs/run-1/state",
            headers=_headers(service_token, admin_token),
            json={
                "state": "published",
                "processed_rows": 42,
                "dataset_meta_path": "data/processed/runs/run-1/dataset_meta.json",
                "manifest_uri": "s3://bucket/hh/manifests/run=run-1/manifest.json",
                "quality_report_uri": "s3://bucket/hh/manifests/run=run-1/quality_report.json",
                "product_eligibility": {"search": {"eligible": True}},
                "source_capability_ref": build_source_capability_ref(
                    source_mode="fixture",
                    use_case="current_snapshot",
                    capability_status="supported",
                    evidence_type="test_fixture",
                ),
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "published"
        assert body["processed_rows"] == 42
        assert body["dataset_meta_path"] == "data/processed/runs/run-1/dataset_meta.json"
        assert body["product_eligibility"]["search"]["eligible"] is True
        assert body["source_capability_ref"]["source_mode"] == "fixture"
        assert body["finished_at"]

        latest = client.get("/v1/admin/data-runs/latest", headers=_headers(service_token, admin_token))
        assert latest.status_code == 200
        assert latest.json()["latest"]["run_id"] == "run-1"

        active = client.get("/v1/admin/data-runs/active", headers=_headers(service_token, admin_token))
        assert active.status_code == 200
        active_body = active.json()
        assert active_body["state"] == "published"
        assert active_body["active"]["run_id"] == "run-1"
        assert active_body["active"]["manifest_uri"] == "s3://bucket/hh/manifests/run=run-1/manifest.json"

        response = client.post(
            "/v1/admin/data-runs/run-2/state",
            headers=_headers(service_token, admin_token),
            json={"state": "published", "processed_rows": 24},
        )
        assert response.status_code == 200
        activated = client.post("/v1/admin/data-runs/run-1/activate", headers=_headers(service_token, admin_token))
        assert activated.status_code == 200
        assert activated.json()["active"]["run_id"] == "run-1"

        history = client.get("/v1/admin/data-runs", headers=_headers(service_token, admin_token))
        assert history.status_code == 200
        assert [item["run_id"] for item in history.json()] == ["run-2", "run-1"]


def test_data_run_state_rejects_invalid_state(tmp_path: Path, service_token: str, admin_token: str) -> None:
    app = _app(f"sqlite+aiosqlite:///{tmp_path / 'data_runs_invalid.db'}", service_token, admin_token)
    asyncio.run(_create_schema(app))

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/data-runs/run-1/state",
            headers=_headers(service_token, admin_token),
            json={"state": "done"},
        )

    assert response.status_code == 422
    assert "Invalid data run state" in response.json()["error"]


def test_data_run_state_rejects_regression_after_progress(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
) -> None:
    app = _app(f"sqlite+aiosqlite:///{tmp_path / 'data_runs_regression.db'}", service_token, admin_token)
    asyncio.run(_create_schema(app))

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/data-runs/run-1/state",
            headers=_headers(service_token, admin_token),
            json={"state": "processed_validated"},
        )
        assert response.status_code == 200

        response = client.post(
            "/v1/admin/data-runs/run-1/state",
            headers=_headers(service_token, admin_token),
            json={"state": "raw_validated"},
        )

    assert response.status_code == 422
    assert "Invalid data run transition" in response.json()["error"]


def test_data_run_state_is_visible_in_health(tmp_path: Path, service_token: str, admin_token: str) -> None:
    app = _app(f"sqlite+aiosqlite:///{tmp_path / 'data_runs_health.db'}", service_token, admin_token)
    asyncio.run(_create_schema(app))
    asyncio.run(
        upsert_data_run_state(
            app.state.session_maker,
            run_id="run-health",
            state="failed",
            source="test",
            error_msg="boom",
        )
    )

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data_run"]["state"] == "failed"
    assert body["data_run"]["latest"]["run_id"] == "run-health"
    assert body["data_run"]["active"] is None


def test_active_data_run_is_visible_in_health(tmp_path: Path, service_token: str, admin_token: str) -> None:
    app = _app(f"sqlite+aiosqlite:///{tmp_path / 'active_data_runs_health.db'}", service_token, admin_token)
    asyncio.run(_create_schema(app))
    asyncio.run(
        upsert_data_run_state(
            app.state.session_maker,
            run_id="run-active",
            state="published",
            source="test",
            processed_rows=100,
            manifest_uri="s3://bucket/hh/manifests/run=run-active/manifest.json",
        )
    )

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data_run"]["active"]["run_id"] == "run-active"
    assert body["data_run"]["active"]["state"] == "published"


def test_data_run_state_updates_prometheus_metrics(tmp_path: Path, service_token: str, admin_token: str) -> None:
    app = _app(f"sqlite+aiosqlite:///{tmp_path / 'data_runs_metrics.db'}", service_token, admin_token)
    asyncio.run(_create_schema(app))

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/data-runs/run-metrics/state",
            headers=_headers(service_token, admin_token),
            json={"state": "published", "source": "metrics-test", "raw_rows": 120, "processed_rows": 100},
        )
        assert response.status_code == 200

        metrics = client.get("/internal/metrics")

    assert metrics.status_code == 200
    text = metrics.text
    assert 'skillra_data_run_state{source="metrics-test",state="published"} 1.0' in text
    assert 'skillra_data_run_raw_rows_total{source="metrics-test"} 120.0' in text
    assert 'skillra_data_run_processed_rows_total{source="metrics-test"} 100.0' in text
    assert 'skillra_data_run_last_success_timestamp_seconds{source="metrics-test"}' in text
