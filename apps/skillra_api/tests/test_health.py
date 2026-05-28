"""Health endpoint tests for the Skillra API skeleton."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.main import create_app  # noqa: E402
from skillra_api.routers import health as health_router  # noqa: E402


def test_health_endpoints_return_expected_status_when_data_missing() -> None:
    settings = Settings(log_level="CRITICAL", database_url=None, redis_url=None, meilisearch_url="")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "Skillra API" in body["message"]
        assert body["version"] == app.version
        assert body["runtime_env"] == "local"
        assert body["public_base_url"] is None

        v1_response = client.get("/v1/health")
        assert v1_response.status_code == 200
        v1_body = v1_response.json()
        assert v1_body["status"] == "degraded"
        assert v1_body["runtime_env"] == "local"
        assert v1_body["public_base_url"] is None
        assert v1_body["datastore_status"] == "error"
        assert v1_body["datastore"]["ready"] is False
        assert v1_body["database"] == "not_configured"
        assert v1_body["migrations"]["status"] == "not_configured"


def test_health_endpoints_expose_runtime_contour_marker() -> None:
    settings = Settings(
        log_level="CRITICAL",
        runtime_env="staging",
        public_base_url="https://staging.skillra.ru/",
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/health")
        v1_response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["runtime_env"] == "staging"
    assert response.json()["public_base_url"] == "https://staging.skillra.ru"
    assert v1_response.status_code == 200
    assert v1_response.json()["runtime_env"] == "staging"
    assert v1_response.json()["public_base_url"] == "https://staging.skillra.ru"


def test_v1_health_reports_migration_degradation() -> None:
    settings = Settings(log_level="CRITICAL", database_url=None, redis_url=None, meilisearch_url="")
    app = create_app(settings)
    with TestClient(app) as client:
        client.app.state.migration_status = {"status": "degraded", "current": "001", "head": "002"}

        response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["migrations"] == {"status": "degraded", "current": "001", "head": "002"}


def test_v1_ready_returns_503_when_dependency_health_is_degraded() -> None:
    settings = Settings(log_level="CRITICAL", database_url=None, redis_url=None, meilisearch_url="")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/v1/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["datastore_status"] == "error"


def test_v1_health_rechecks_degraded_meilisearch_state(monkeypatch) -> None:
    async def fake_meilisearch_status(settings: Settings) -> str:
        return "ok"

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(meilisearch_status="degraded")))
    settings = Settings(log_level="CRITICAL", meilisearch_url="http://meilisearch:7700")
    monkeypatch.setattr(health_router, "_meilisearch_status", fake_meilisearch_status)

    status = asyncio.get_event_loop().run_until_complete(health_router._current_meilisearch_status(request, settings))

    assert status == "ok"
    assert request.app.state.meilisearch_status == "ok"


def test_root_endpoint_returns_manual_index() -> None:
    settings = Settings(log_level="CRITICAL")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["docs"] == "/docs"
        assert body["health"] == "/health"


def test_auth_check_validates_service_token(service_token: str) -> None:
    settings = Settings(api_token=service_token, log_level="CRITICAL")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/v1/auth/check", headers={"X-Skillra-Token": service_token})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        rejected = client.get("/v1/auth/check", headers={"X-Skillra-Token": "wrong-token"})
        assert rejected.status_code == 401


def test_cors_preflight_allows_local_web_origin(service_token: str) -> None:
    settings = Settings(api_token=service_token, log_level="CRITICAL")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.options(
            "/v1/auth/check",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Skillra-Token",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_health_endpoint_returns_request_id_header() -> None:
    settings = Settings(log_level="CRITICAL")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.headers.get("X-Request-ID")


def test_health_endpoint_propagates_incoming_request_id() -> None:
    settings = Settings(log_level="CRITICAL")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "test-id"})

        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == "test-id"


def test_request_logging_includes_request_id(caplog) -> None:
    settings = Settings(log_level="INFO")
    app = create_app(settings)
    with TestClient(app) as client:
        caplog.set_level(logging.INFO, logger="skillra_api.middlewares.request_logging")

        response = client.get("/health", headers={"X-Request-ID": "req-abc"})

        assert response.status_code == 200

        handled_logs = [record for record in caplog.records if "Handled request" in record.message]
        assert handled_logs
        log_entry = handled_logs[0]
        assert "method=GET" in log_entry.message
        assert "path=/health" in log_entry.message
        assert "status=200" in log_entry.message
        assert "request_id=req-abc" in log_entry.message
