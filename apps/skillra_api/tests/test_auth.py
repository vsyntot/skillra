from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.main import create_app  # noqa: E402


def _make_app(tmp_path: Path, service_token: str, admin_token: str) -> FastAPI:
    """Create an app with parquet fixtures pre-populated."""
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"

    pd.DataFrame({"primary_role": ["data"]}).to_parquet(features_path)
    pd.DataFrame({"primary_role": ["data"], "vacancy_count": [1]}).to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        api_token=service_token,
        admin_token=admin_token,
        database_url="",
        redis_url="",
        meilisearch_url="",
        data_watch_interval=0,
    )
    return create_app(settings)


def test_requests_without_service_token_are_rejected(tmp_path: Path, service_token: str, admin_token: str) -> None:
    with TestClient(_make_app(tmp_path, service_token, admin_token)) as client:
        response = client.get("/v1/meta/roles")

        assert response.status_code == 401
        assert response.json() == {
            "error_code": "AUTHORIZATION_REQUIRED",
            "message": "X-Skillra-Token header required.",
            "details": {},
        }


def test_error_responses_match_contract(tmp_path: Path, service_token: str, admin_token: str) -> None:
    with TestClient(_make_app(tmp_path, service_token, admin_token)) as client:
        response = client.get("/v1/meta/roles")

        assert response.status_code == 401
        payload = response.json()
        assert set(payload) == {"error_code", "message", "details"}
        assert isinstance(payload["error_code"], str)
        assert isinstance(payload["message"], str)
        assert isinstance(payload["details"], dict)


def test_requests_with_service_token_succeed(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
    auth_headers: dict[str, str],
) -> None:
    with TestClient(_make_app(tmp_path, service_token, admin_token)) as client:
        client.headers.update(auth_headers)
        response = client.get("/v1/meta/roles")

        assert response.status_code == 200


def test_requests_with_invalid_service_token_are_rejected(tmp_path: Path, service_token: str, admin_token: str) -> None:
    with TestClient(_make_app(tmp_path, service_token, admin_token)) as client:
        client.headers.update({"X-Skillra-Token": "wrong-token"})
        response = client.get("/v1/meta/roles")

        assert response.status_code == 401
        assert response.json() == {
            "error_code": "INVALID_USER_API_KEY",
            "message": "Invalid or revoked user API key.",
            "details": {},
        }


def test_admin_without_admin_token_is_forbidden(
    tmp_path: Path, service_token: str, admin_token: str, auth_headers: dict[str, str]
) -> None:
    with TestClient(_make_app(tmp_path, service_token, admin_token)) as client:
        client.headers.update(auth_headers)
        response = client.post("/v1/admin/reload-data")

        assert response.status_code == 403
        assert response.json() == {
            "error_code": "ADMIN_TOKEN_REQUIRED",
            "message": "Admin token is required for admin endpoints.",
            "details": {},
        }


def test_admin_with_invalid_admin_token_is_forbidden(
    tmp_path: Path, service_token: str, admin_token: str, auth_headers: dict[str, str]
) -> None:
    with TestClient(_make_app(tmp_path, service_token, admin_token)) as client:
        client.headers.update(auth_headers)
        client.headers["X-Admin-Token"] = "invalid-admin"
        response = client.post("/v1/admin/reload-data")

        assert response.status_code == 403
        assert response.json() == {
            "error_code": "ADMIN_TOKEN_REQUIRED",
            "message": "Admin token is required for admin endpoints.",
            "details": {},
        }


def test_admin_with_valid_tokens_succeeds(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
    admin_headers: dict[str, str],
) -> None:
    with TestClient(_make_app(tmp_path, service_token, admin_token)) as client:
        client.headers.update(admin_headers)
        response = client.post("/v1/admin/reload-data")

        assert response.status_code == 200
        assert response.json()["status"] == "reloaded"


# ---------------------------------------------------------------------------
# TASK-03 (Sprint-004): SERVICE_TOKEN_NOT_CONFIGURED → 503
# ---------------------------------------------------------------------------
def test_service_token_not_configured_returns_503() -> None:
    """Service-only endpoints still expose missing service token configuration."""
    settings = Settings(log_level="CRITICAL", api_token="")
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/auth/check")

        assert response.status_code == 503
        payload = response.json()
        assert payload["error_code"] == "SERVICE_TOKEN_NOT_CONFIGURED"
        assert isinstance(payload["message"], str)


def test_admin_token_not_configured_returns_503(auth_headers: dict[str, str]) -> None:
    """When SKILLRA_ADMIN_TOKEN is not set, admin endpoints must return 503."""
    settings = Settings(log_level="CRITICAL", api_token="test-token", admin_token="")
    with TestClient(create_app(settings)) as client:
        client.headers.update({"X-Skillra-Token": "test-token"})
        response = client.post("/v1/admin/reload-data")

        assert response.status_code == 503
        payload = response.json()
        assert payload["error_code"] == "ADMIN_TOKEN_NOT_CONFIGURED"
        assert isinstance(payload["message"], str)
