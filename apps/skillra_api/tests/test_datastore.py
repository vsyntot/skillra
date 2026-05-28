from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.main import create_app  # noqa: E402


def test_health_reports_loaded_parquet(tmp_path: Path, service_token: str) -> None:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"
    dataset_meta_path = tmp_path / "dataset_meta.json"

    pd.DataFrame({"a": [1]}).to_parquet(features_path)
    pd.DataFrame({"b": [2]}).to_parquet(market_view_path)

    dataset_meta = {
        "generated_at_utc": "2024-01-01T00:00:00+00:00",
        "features_rows": 1,
        "market_view_rows": 1,
        "features_path": str(features_path),
        "market_view_path": str(market_view_path),
    }
    dataset_meta_path.write_text(json.dumps(dataset_meta), encoding="utf-8")

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        dataset_meta_path=str(dataset_meta_path),
        api_token=service_token,
        admin_token="secret",
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["datastore_status"] == "ok"
        assert body["datastore"]["ready"] is True
        assert body["datastore"]["datasets"]["features"]["loaded"] is True
        assert body["datastore"]["datasets"]["market_view"]["mtime"] is not None
        assert body["datastore"]["dataset_meta"] == dataset_meta


def test_admin_reload_requires_token(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
    auth_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"

    pd.DataFrame({"a": [1]}).to_parquet(features_path)
    pd.DataFrame({"b": [2]}).to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        api_token=service_token,
        admin_token=admin_token,
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update(auth_headers)

        missing_token_response = client.post("/v1/admin/reload-data")
        assert missing_token_response.status_code == 403

        wrong_token_response = client.post("/v1/admin/reload-data", headers={"X-Admin-Token": "wrong"})
        assert wrong_token_response.status_code == 403

        ok_response = client.post("/v1/admin/reload-data", headers=admin_headers)
        assert ok_response.status_code == 200
        body = ok_response.json()
        assert body["status"] == "reloaded"
        assert body["datastore"]["ready"] is True


# ---------------------------------------------------------------------------
# TASK-04 (Sprint-004): DataStore meta cache is cleared on reload
# ---------------------------------------------------------------------------
def test_meta_cache_is_cleared_on_reload(
    tmp_path: Path,
    service_token: str,
    admin_token: str,
    admin_headers: dict[str, str],
) -> None:
    """Verify that DataStore.get_cached_meta() reflects fresh data after reload."""
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"

    pd.DataFrame({"primary_role": ["data"], "grade_final": ["junior"]}).to_parquet(features_path)
    pd.DataFrame({"primary_role": ["data"], "vacancy_count": [1]}).to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        api_token=service_token,
        admin_token=admin_token,
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    datastore = app.state.datastore
    with TestClient(app) as client:
        client.headers.update({"X-Skillra-Token": service_token})

        # Warm the cache via /v1/meta/roles
        roles_response = client.get("/v1/meta/roles")
        assert roles_response.status_code == 200
        assert datastore._meta_cache  # cache populated

        # Reload clears the cache
        reload_response = client.post("/v1/admin/reload-data", headers=admin_headers)
        assert reload_response.status_code == 200
        assert not datastore._meta_cache  # cache cleared after reload


def test_watch_reload_reloads_only_after_mtime_change(tmp_path: Path, service_token: str) -> None:
    async def _run() -> None:
        features_path = tmp_path / "hh_features.parquet"
        market_view_path = tmp_path / "market_view.parquet"
        pd.DataFrame({"a": [1]}).to_parquet(features_path)
        pd.DataFrame({"b": [2]}).to_parquet(market_view_path)

        settings = Settings(
            log_level="CRITICAL",
            features_path=str(features_path),
            market_view_path=str(market_view_path),
            api_token=service_token,
            database_url=None,
            redis_url=None,
            meilisearch_url="",
        )
        datastore = create_app(settings).state.datastore
        datastore.areload = AsyncMock()  # type: ignore[method-assign]

        task = asyncio.create_task(datastore.watch_reload(check_interval=0.02))
        try:
            await asyncio.sleep(0.05)
            datastore.areload.assert_not_awaited()

            pd.DataFrame({"a": [2]}).to_parquet(features_path)
            await asyncio.sleep(0.05)
            datastore.areload.assert_awaited()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(_run())
