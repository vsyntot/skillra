from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient
from skillra_api.config import Settings
from skillra_api.constants import ADMIN_TOKEN_HEADER, SERVICE_TOKEN_HEADER
from skillra_api.db import Base
from skillra_api.main import create_app
from skillra_api.routers import admin
from skillra_api.routers import health as health_router
from skillra_api.services.data_runs import upsert_data_run_state


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_processed_run(base_dir: Path, run_id: str) -> dict[str, object]:
    run_dir = base_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    features_path = run_dir / "hh_features.parquet"
    market_view_path = run_dir / "market_view.parquet"
    dataset_meta_path = run_dir / "dataset_meta.json"
    pd.DataFrame(
        {
            "hh_vacancy_id": [run_id],
            "title": ["Data Analyst"],
            "primary_role": ["data"],
            "grade_final": ["junior"],
            "city_tier": ["Moscow"],
            "work_mode": ["remote"],
        }
    ).to_parquet(features_path)
    pd.DataFrame({"primary_role": ["data"], "grade_final": ["junior"], "city_tier": ["Moscow"]}).to_parquet(
        market_view_path
    )
    dataset_meta = {
        "run_id": run_id,
        "features_path": str(features_path),
        "market_view_path": str(market_view_path),
        "features_rows": 1,
        "market_view_rows": 1,
    }
    dataset_meta_path.write_text(json.dumps(dataset_meta), encoding="utf-8")
    artifacts = [
        {"path": str(dataset_meta_path), "sha256": _sha256(dataset_meta_path)},
        {"path": str(features_path), "sha256": _sha256(features_path)},
        {"path": str(market_view_path), "sha256": _sha256(market_view_path)},
    ]
    return {
        "dataset_meta_path": str(dataset_meta_path),
        "artifact_uris": {"artifacts": artifacts},
    }


async def _publish_bad_run(app, dataset_meta_path: str) -> None:
    await upsert_data_run_state(
        app.state.session_maker,
        run_id="run-bad",
        state="published",
        source="test",
        processed_rows=1,
        dataset_meta_path=dataset_meta_path,
        artifact_uris={"artifacts": []},
    )


def test_indexer_status_requires_admin_token(tmp_path: Path, service_token: str, admin_token: str) -> None:
    app = _app(f"sqlite+aiosqlite:///{tmp_path / 'status_auth.db'}", service_token, admin_token)
    asyncio.run(_create_schema(app))

    with TestClient(app) as client:
        response = client.get("/v1/admin/indexer-status", headers={SERVICE_TOKEN_HEADER: service_token})

    assert response.status_code == 403


def test_indexer_status_persists_after_restart(tmp_path: Path, service_token: str, admin_token: str) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'status.db'}"
    app1 = _app(db_url, service_token, admin_token)
    asyncio.run(_create_schema(app1))

    run_id = asyncio.run(admin._create_indexer_run(app1.state.session_maker, "test"))
    asyncio.run(admin._set_indexer_success(app1.state.session_maker, run_id, {"inserted": 3, "indexed": 2}))

    app2 = _app(db_url, service_token, admin_token)
    with TestClient(app2) as client:
        response = client.get(
            "/v1/admin/indexer-status",
            headers={SERVICE_TOKEN_HEADER: service_token, ADMIN_TOKEN_HEADER: admin_token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["source"] == "test"
    assert body["inserted"] == 3
    assert body["indexed"] == 2
    assert body["finished_at"]


def test_indexer_status_failure_stored(tmp_path: Path, service_token: str, admin_token: str) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'status_failure.db'}"
    app = _app(db_url, service_token, admin_token)
    asyncio.run(_create_schema(app))

    run_id = asyncio.run(admin._create_indexer_run(app.state.session_maker, "test"))
    asyncio.run(admin._set_indexer_failure(app.state.session_maker, run_id, RuntimeError("boom")))

    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/indexer-status",
            headers={SERVICE_TOKEN_HEADER: service_token, ADMIN_TOKEN_HEADER: admin_token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["source"] == "test"
    assert body["error_msg"] == "boom"
    assert body["finished_at"]


def test_indexer_status_extracts_dataset_run_id_from_source(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'status_dataset_run.db'}"
    app = _app(db_url, service_token, admin_token)
    asyncio.run(_create_schema(app))

    run_id = asyncio.run(admin._create_indexer_run(app.state.session_maker, "reload:20260519T161849Z"))
    asyncio.run(admin._set_indexer_success(app.state.session_maker, run_id, {"inserted": 3, "indexed": 3}))

    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/indexer-status",
            headers={SERVICE_TOKEN_HEADER: service_token, ADMIN_TOKEN_HEADER: admin_token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "reload:20260519T161849Z"
    assert body["dataset_run_id"] == "20260519T161849Z"


def test_indexer_status_returns_first_class_dataset_run_id(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'status_dataset_column.db'}"
    app = _app(db_url, service_token, admin_token)
    asyncio.run(_create_schema(app))

    run_id = asyncio.run(
        admin._create_indexer_run(
            app.state.session_maker,
            "reload",
            dataset_run_id="20260519T161849Z",
        )
    )
    asyncio.run(admin._set_indexer_success(app.state.session_maker, run_id, {"inserted": 3, "indexed": 3}))

    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/indexer-status",
            headers={SERVICE_TOKEN_HEADER: service_token, ADMIN_TOKEN_HEADER: admin_token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "reload"
    assert body["dataset_run_id"] == "20260519T161849Z"


def test_reload_data_restores_previous_datastore_when_indexer_fails(monkeypatch) -> None:
    class FakeDataStore:
        def __init__(self) -> None:
            self.run_id = "old-run"
            self.restored = False

        def snapshot_state(self) -> str:
            return self.run_id

        async def areload(self) -> None:
            self.run_id = "new-run"

        def restore_state(self, snapshot: str) -> None:
            self.run_id = snapshot
            self.restored = True

        def get_dataset_meta(self) -> dict[str, str]:
            return {"run_id": self.run_id}

        def status(self) -> dict[str, object]:
            return {"ready": True, "dataset_meta": {"run_id": self.run_id}}

    class FakeRedis:
        def __init__(self) -> None:
            self.published: list[tuple[str, str]] = []

        async def publish(self, channel: str, payload: str) -> None:
            self.published.append((channel, payload))

    async def fail_indexer(*_: object, **__: object) -> dict[str, object]:
        raise RuntimeError("index completeness failed")

    datastore = FakeDataStore()
    redis = FakeRedis()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_maker=object())))
    settings = Settings(log_level="CRITICAL", api_token="service", admin_token="admin", meilisearch_url="")
    monkeypatch.setattr(admin, "_run_vacancy_indexer", fail_indexer)

    response = asyncio.run(admin.reload_data(request, datastore, redis, settings))

    assert response.status_code == 500
    body = json.loads(response.body)
    assert body["status"] == "reload_failed"
    assert body["dataset_run_id"] == "new-run"
    assert body["served_dataset_run_id"] == "old-run"
    assert datastore.run_id == "old-run"
    assert datastore.restored is True
    assert redis.published == []


def test_reload_data_uses_active_registry_run_instead_of_latest(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
    monkeypatch,
) -> None:
    active_artifacts = _write_processed_run(tmp_path / "processed", "run-active")
    latest_artifacts = _write_processed_run(tmp_path / "processed", "run-latest")
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'active_reload.db'}"
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        admin_token=admin_token,
        database_url=db_url,
        redis_url="",
        meilisearch_url="",
        data_watch_interval=0,
        dataset_meta_path=str(latest_artifacts["dataset_meta_path"]),
        features_path=str(Path(str(latest_artifacts["dataset_meta_path"])).parent / "hh_features.parquet"),
        market_view_path=str(Path(str(latest_artifacts["dataset_meta_path"])).parent / "market_view.parquet"),
    )
    app = create_app(settings)
    asyncio.run(_create_schema(app))
    asyncio.run(
        upsert_data_run_state(
            app.state.session_maker,
            run_id="run-active",
            state="published",
            source="test",
            processed_rows=1,
            dataset_meta_path=str(active_artifacts["dataset_meta_path"]),
            artifact_uris=active_artifacts["artifact_uris"],  # type: ignore[arg-type]
        )
    )

    async def fake_indexer(*_: object, **__: object) -> dict[str, object]:
        return {"run_id": 1, "dataset_run_id": "run-active", "status": "success", "inserted": 1, "indexed": 1}

    monkeypatch.setattr(admin, "_run_vacancy_indexer", fake_indexer)

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/reload-data",
            headers={"X-Skillra-Token": service_token, "X-Admin-Token": admin_token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_run_id"] == "run-active"
    assert body["active_dataset_run_id"] == "run-active"
    assert set(body["verified_artifacts"]) == {"dataset_meta", "features", "market_view"}
    assert body["datastore"]["dataset_meta"]["run_id"] == "run-active"


def test_reload_data_rejects_active_artifact_without_checksum_and_keeps_previous_run(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
) -> None:
    latest_artifacts = _write_processed_run(tmp_path / "processed", "run-latest")
    bad_meta = tmp_path / "processed" / "runs" / "run-bad" / "dataset_meta.json"
    bad_meta.parent.mkdir(parents=True)
    bad_meta.write_text(json.dumps({"run_id": "run-bad"}), encoding="utf-8")
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'bad_active_reload.db'}"
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        admin_token=admin_token,
        database_url=db_url,
        redis_url="",
        meilisearch_url="",
        data_watch_interval=0,
        dataset_meta_path=str(latest_artifacts["dataset_meta_path"]),
        features_path=str(Path(str(latest_artifacts["dataset_meta_path"])).parent / "hh_features.parquet"),
        market_view_path=str(Path(str(latest_artifacts["dataset_meta_path"])).parent / "market_view.parquet"),
    )
    app = create_app(settings)
    asyncio.run(_create_schema(app))

    with TestClient(app) as client:
        client.portal.call(_publish_bad_run, app, str(bad_meta))
        response = client.post(
            "/v1/admin/reload-data",
            headers={"X-Skillra-Token": service_token, "X-Admin-Token": admin_token},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "active_dataset_artifact_invalid"
    assert body["served_dataset_run_id"] == "run-latest"
    assert body["datastore"]["dataset_meta"]["run_id"] == "run-latest"


def test_search_publish_status_degrades_on_failed_indexer_run(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'search_publish_health.db'}"
    app = _app(db_url, service_token, admin_token)
    asyncio.run(_create_schema(app))

    run_id = asyncio.run(
        admin._create_indexer_run(
            app.state.session_maker,
            "reload",
            dataset_run_id="run-health",
        )
    )
    asyncio.run(admin._set_indexer_failure(app.state.session_maker, run_id, RuntimeError("boom")))

    status = asyncio.run(health_router._search_publish_status(app.state.session_maker, "run-health"))

    assert status["status"] == "degraded"
    assert status["dataset_run_id"] == "run-health"
    assert status["error_msg"] == "boom"


def test_search_publish_status_keeps_readiness_ok_during_verified_reindex(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'search_publish_reindex.db'}"
    app = _app(db_url, service_token, admin_token)
    asyncio.run(_create_schema(app))

    success_id = asyncio.run(
        admin._create_indexer_run(
            app.state.session_maker,
            "reload",
            dataset_run_id="run-health",
        )
    )
    asyncio.run(admin._set_indexer_success(app.state.session_maker, success_id, {"inserted": 12, "indexed": 12}))
    asyncio.run(
        admin._create_indexer_run(
            app.state.session_maker,
            "manual",
            dataset_run_id="run-health",
        )
    )

    status = asyncio.run(health_router._search_publish_status(app.state.session_maker, "run-health"))

    assert status["status"] == "ok"
    assert status["dataset_run_id"] == "run-health"
    assert status["source"] == "reload"
    assert status["indexed"] == 12
    assert status["in_progress"] is True
    assert status["latest_status"] == "running"
    assert status["latest_source"] == "manual"
