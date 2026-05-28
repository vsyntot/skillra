"""Meta endpoints tests for Skillra API."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.deps import get_redis_dependency  # noqa: E402
from skillra_api.main import create_app  # noqa: E402


@pytest.fixture()
def meta_client(tmp_path: Path, service_token: str, auth_headers: dict[str, str]) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"
    dataset_meta_path = tmp_path / "dataset_meta.json"

    features_df = pd.DataFrame(
        {
            "primary_role": ["data", "analyst", "ml"],
            "grade_final": ["junior", "senior", "middle"],
            "city_tier": ["Moscow", "SPb", "Million+"],
            "country": ["Russia", "Russia", "Kazakhstan"],
            "region": ["Moscow", "Saint Petersburg", "Almaty"],
            "city_normalized": ["Moscow", "Saint Petersburg", "Almaty"],
            "geo_scope": ["remote", "local", "mixed"],
            "work_mode": ["remote", "office", "hybrid"],
            "skill_python": [True, False, True],
            "skill_sql": [True, True, False],
            "has_management": [False, True, False],
        }
    )
    features_df.to_parquet(features_path)

    market_view_df = pd.DataFrame(
        {
            "primary_role": ["data", "analyst", "ml"],
            "city_tier": ["Moscow", "SPb", "Million+"],
            "country": ["Russia", "Russia", "Kazakhstan"],
            "region": ["Moscow", "Saint Petersburg", "Almaty"],
            "city_normalized": ["Moscow", "Saint Petersburg", "Almaty"],
            "geo_scope": ["remote", "local", "mixed"],
            "grade_final": ["junior", "senior", "middle"],
            "domain": ["analytics", "bi", "mlops"],
            "vacancy_count_total": [10, 5, 3],
            "vacancy_count_salary": [10, 5, 3],
            "salary_median": [100, 80, 120],
            "salary_q25": [90, 70, 110],
            "salary_q75": [110, 90, 130],
            "junior_friendly_share": [0.2, 0.1, 0.15],
            "remote_share": [0.5, 0.3, 0.4],
            "median_tech_stack_size": [5, 4, 6],
            "vacancy_count": [10, 5, 3],
        }
    )
    market_view_df.to_parquet(market_view_path)

    dataset_meta = {
        "generated_at_utc": "2024-01-01T00:00:00+00:00",
        "features_rows": len(features_df),
        "market_view_rows": len(market_view_df),
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
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update(auth_headers)
        client.dataset_meta = dataset_meta  # type: ignore[attr-defined]
        yield client


def test_meta_roles(meta_client: TestClient) -> None:
    response = meta_client.get("/v1/meta/roles")
    assert response.status_code == 200
    assert response.json() == {"roles": ["analyst", "data", "ml"]}


def test_meta_grades(meta_client: TestClient) -> None:
    response = meta_client.get("/v1/meta/grades")
    assert response.status_code == 200
    assert response.json() == {"grades": ["junior", "middle", "senior"]}


def test_meta_city_tiers(meta_client: TestClient) -> None:
    response = meta_client.get("/v1/meta/city-tiers")
    assert response.status_code == 200
    assert response.json() == {"city_tiers": ["Million+", "Moscow", "SPb"]}


def test_meta_geography(meta_client: TestClient) -> None:
    countries = meta_client.get("/v1/meta/countries")
    regions = meta_client.get("/v1/meta/regions")
    cities = meta_client.get("/v1/meta/cities")
    geo_scopes = meta_client.get("/v1/meta/geo-scopes")

    assert countries.status_code == 200
    assert countries.json() == {"countries": ["Kazakhstan", "Russia"]}
    assert regions.status_code == 200
    assert regions.json() == {"regions": ["Almaty", "Moscow", "Saint Petersburg"]}
    assert cities.status_code == 200
    assert cities.json() == {"cities": ["Almaty", "Moscow", "Saint Petersburg"]}
    assert geo_scopes.status_code == 200
    assert geo_scopes.json() == {"geo_scopes": ["local", "mixed", "remote"]}


def test_meta_work_modes(meta_client: TestClient) -> None:
    response = meta_client.get("/v1/meta/work-modes")
    assert response.status_code == 200
    assert response.json() == {"work_modes": ["hybrid", "office", "remote"]}


def test_meta_domains(meta_client: TestClient) -> None:
    response = meta_client.get("/v1/meta/domains")
    assert response.status_code == 200
    assert response.json() == {"domains": ["analytics", "bi", "mlops"]}


def test_meta_skills(meta_client: TestClient) -> None:
    response = meta_client.get("/v1/meta/skills")
    assert response.status_code == 200
    assert response.json() == {
        "skills": ["management", "python", "sql"],
        "total": 3,
        "limit": 100,
        "offset": 0,
    }


def test_meta_skills_pagination_and_search(meta_client: TestClient) -> None:
    first_page = meta_client.get("/v1/meta/skills", params={"limit": 1, "offset": 0})
    assert first_page.status_code == 200
    assert first_page.json() == {"skills": ["management"], "total": 3, "limit": 1, "offset": 0}

    second_page = meta_client.get("/v1/meta/skills", params={"limit": 1, "offset": 1})
    assert second_page.status_code == 200
    assert second_page.json() == {"skills": ["python"], "total": 3, "limit": 1, "offset": 1}

    search = meta_client.get("/v1/meta/skills", params={"search": "PY"})
    assert search.status_code == 200
    assert search.json() == {"skills": ["python"], "total": 1, "limit": 100, "offset": 0}


@pytest.mark.parametrize(
    ("endpoint", "key"),
    [
        ("/v1/meta/roles", "roles"),
        ("/v1/meta/grades", "grades"),
        ("/v1/meta/city-tiers", "city_tiers"),
        ("/v1/meta/countries", "countries"),
        ("/v1/meta/regions", "regions"),
        ("/v1/meta/cities", "cities"),
        ("/v1/meta/geo-scopes", "geo_scopes"),
        ("/v1/meta/work-modes", "work_modes"),
        ("/v1/meta/domains", "domains"),
        ("/v1/meta/skills", "skills"),
    ],
)
def test_meta_endpoints_return_lists_of_strings(meta_client: TestClient, endpoint: str, key: str) -> None:
    response = meta_client.get(endpoint)

    assert response.status_code == 200
    payload = response.json()
    assert key in payload
    value = payload[key]
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)


def test_meta_dataset(meta_client: TestClient) -> None:
    response = meta_client.get("/v1/meta/dataset")
    assert response.status_code == 200
    body = response.json()
    # TASK-02 (C-GAP-03): DatasetMetaResponse with extra="allow" passes through
    # all keys from dataset_meta.json; None fields are excluded (exclude_none=True)
    dataset_meta: dict = meta_client.dataset_meta  # type: ignore[attr-defined]
    for key, value in dataset_meta.items():
        assert body.get(key) == value, f"Missing or wrong key {key!r} in response"


def test_meta_dataset_returns_empty_when_meta_missing(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> None:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"
    dataset_meta_path = tmp_path / "dataset_meta.json"

    pd.DataFrame({"a": [1]}).to_parquet(features_path)
    pd.DataFrame({"b": [2]}).to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        dataset_meta_path=str(dataset_meta_path),
        api_token=service_token,
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update(auth_headers)

        response = client.get("/v1/meta/dataset")
        assert response.status_code == 200
        # TASK-02 (C-GAP-03): when meta is missing, DatasetMetaResponse returns
        # schema with all None fields excluded via response_model_exclude_none=True
        assert response.json() == {}


def test_meta_endpoint_returns_503_when_data_missing(auth_headers: dict[str, str], service_token: str) -> None:
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update(auth_headers)

        response = client.get("/v1/meta/roles")
        assert response.status_code == 503
        assert response.json()["error_code"] == "DATA_UNAVAILABLE"


# ---------------------------------------------------------------------------
# TASK-04 (Sprint-004): meta cache is populated and invalidated on reload()
# ---------------------------------------------------------------------------


def test_meta_cache_is_invalidated_on_reload(tmp_path: Path, service_token: str, auth_headers: dict[str, str]) -> None:
    """DataStore._meta_cache must be cleared on reload so meta returns fresh data."""
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"

    pd.DataFrame({"primary_role": ["data"], "grade_final": ["junior"]}).to_parquet(features_path)
    pd.DataFrame({"primary_role": ["data"], "vacancy_count": [1]}).to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        api_token=service_token,
        admin_token="test-admin",
        database_url=None,
        redis_url=None,
        meilisearch_url="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update(auth_headers)

        # First call populates cache.
        r1 = client.get("/v1/meta/roles")
        assert r1.status_code == 200
        roles_before = r1.json()["roles"]

        # Reload-data clears the cache.
        reload_resp = client.post("/v1/admin/reload-data", headers={"X-Admin-Token": "test-admin"})
        assert reload_resp.status_code == 200

        # Second call after reload must still return valid data (cache repopulated).
        r2 = client.get("/v1/meta/roles")
        assert r2.status_code == 200
        assert r2.json()["roles"] == roles_before


class FakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.storage.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls += 1
        self.storage[key] = value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.set_calls += 1
        self.storage[key] = value

    async def scan_iter(self, match: str) -> Any:
        prefix = match.rstrip("*")
        for key in list(self.storage):
            if key.startswith(prefix):
                yield key

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.storage.pop(key, None)


def test_meta_skills_uses_redis_cache(meta_client: TestClient) -> None:
    fake_redis = FakeRedis()
    meta_client.app.dependency_overrides[get_redis_dependency] = lambda: fake_redis
    try:
        first = meta_client.get("/v1/meta/skills", params={"limit": 2})
        assert first.status_code == 200
        assert fake_redis.set_calls == 1

        second = meta_client.get("/v1/meta/skills", params={"limit": 2})
        assert second.status_code == 200
        assert second.json() == first.json()
        assert fake_redis.get_calls == 2
        assert fake_redis.set_calls == 1
    finally:
        meta_client.app.dependency_overrides.pop(get_redis_dependency, None)


def test_meta_redis_cache_applies_to_all_list_endpoints(meta_client: TestClient) -> None:
    fake_redis = FakeRedis()
    meta_client.app.dependency_overrides[get_redis_dependency] = lambda: fake_redis
    try:
        endpoints = [
            "/v1/meta/roles",
            "/v1/meta/grades",
            "/v1/meta/city-tiers",
            "/v1/meta/work-modes",
            "/v1/meta/domains",
            "/v1/meta/skills",
        ]
        for endpoint in endpoints:
            first = meta_client.get(endpoint)
            second = meta_client.get(endpoint)
            assert first.status_code == 200
            assert second.status_code == 200
            assert second.json() == first.json()
        expected_keys = {
            "meta:roles",
            "meta:grades",
            "meta:city-tiers",
            "meta:work-modes",
            "meta:domains",
            "meta:skills",
        }
        assert expected_keys.issubset(fake_redis.storage)
    finally:
        meta_client.app.dependency_overrides.pop(get_redis_dependency, None)
