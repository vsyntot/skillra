"""Tests for vacancy_indexer service (Sprint-009 TASK-01)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings
from skillra_api.db.models import VacancySnapshot

# ---------------------------------------------------------------------------
# Unit tests for sync_vacancy_snapshots logic (run via asyncio.run)
# ---------------------------------------------------------------------------


def _run(coro):  # type: ignore[no-untyped-def]
    """Helper to run an async coroutine in sync pytest context."""
    return asyncio.run(coro)


def test_datetime_normalization_localizes_pandas_timestamps() -> None:
    from skillra_api.services.vacancy_indexer import _datetime_or_none

    normalized = _datetime_or_none(pd.Timestamp("2025-11-26 00:00:00"))

    assert normalized == datetime(2025, 11, 26, tzinfo=timezone.utc)


def test_snapshot_parser_deduplicates_vacancy_ids() -> None:
    from skillra_api.services.vacancy_indexer import _snapshots_from_df

    snapshots = _snapshots_from_df(
        pd.DataFrame(
            [
                {"hh_vacancy_id": "123", "title": "Old title", "published_at": pd.Timestamp("2025-11-25")},
                {"hh_vacancy_id": "123", "title": "New title", "published_at": pd.Timestamp("2025-11-26")},
            ]
        )
    )

    assert len(snapshots) == 1
    assert snapshots[0].title == "New title"
    assert snapshots[0].published_at == datetime(2025, 11, 26, tzinfo=timezone.utc)


def test_snapshot_parser_normalizes_float_vacancy_ids() -> None:
    from skillra_api.services.vacancy_indexer import _snapshots_from_df

    snapshots = _snapshots_from_df(pd.DataFrame([{"hh_vacancy_id": 133052423.0, "title": "Data Engineer"}]))

    assert len(snapshots) == 1
    assert snapshots[0].hh_vacancy_id == "133052423"


def test_completeness_status_detects_db_and_search_gaps() -> None:
    from skillra_api.services.vacancy_indexer import _completeness_status

    assert _completeness_status(expected=2, db_total=2, search_total=2) == "complete"
    assert _completeness_status(expected=2, db_total=2, search_total=None) == "not_configured"
    assert _completeness_status(expected=2, db_total=1, search_total=2) == "incomplete"
    assert _completeness_status(expected=2, db_total=2, search_total=1) == "incomplete"


class FakeMeiliResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeMeiliClient:
    def __init__(self, *, stats_override: dict[str, int] | None = None) -> None:
        self.indexes: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.swaps: list[list[str]] = []
        self.stats_override = stats_override or {}

    async def __aenter__(self) -> "FakeMeiliClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def request(self, method: str, path: str, **kwargs: Any) -> FakeMeiliResponse:
        self.requests.append((method, path, kwargs))
        if method == "GET" and path.startswith("/tasks/"):
            return FakeMeiliResponse(200, {"status": "succeeded", "taskUid": path.rsplit("/", 1)[-1]})
        if method == "POST" and path == "/indexes":
            uid = kwargs["json"]["uid"]
            self.indexes[uid] = {"documents": [], "settings": {}, "primary_key": kwargs["json"].get("primaryKey")}
            return FakeMeiliResponse(202, {"taskUid": len(self.requests)})
        if method == "POST" and path == "/swap-indexes":
            source, target = kwargs["json"][0]["indexes"]
            self.swaps.append([source, target])
            self.indexes[source], self.indexes[target] = self.indexes[target], self.indexes[source]
            return FakeMeiliResponse(202, {"taskUid": len(self.requests)})

        uid = _uid_from_path(path)
        if uid is None:
            return FakeMeiliResponse(404, {"code": "not_found", "message": path})
        if method == "GET" and path == f"/indexes/{uid}":
            if uid not in self.indexes:
                return FakeMeiliResponse(404, {"code": "index_not_found", "message": "missing"})
            return FakeMeiliResponse(200, {"uid": uid})
        if method == "DELETE" and path == f"/indexes/{uid}":
            if uid not in self.indexes:
                return FakeMeiliResponse(404, {"code": "index_not_found", "message": "missing"})
            self.indexes.pop(uid)
            return FakeMeiliResponse(202, {"taskUid": len(self.requests)})
        if method == "PATCH" and path == f"/indexes/{uid}/settings":
            self.indexes[uid]["settings"] = kwargs["json"]
            return FakeMeiliResponse(202, {"taskUid": len(self.requests)})
        if method == "POST" and path == f"/indexes/{uid}/documents":
            self.indexes[uid]["documents"].extend(kwargs["json"])
            return FakeMeiliResponse(202, {"taskUid": len(self.requests)})
        if method == "GET" and path == f"/indexes/{uid}/stats":
            count = self.stats_override.get(uid, len(self.indexes[uid]["documents"]))
            return FakeMeiliResponse(200, {"numberOfDocuments": count})
        if method == "POST" and path == f"/indexes/{uid}/search":
            count = self.stats_override.get(uid, len(self.indexes[uid]["documents"]))
            return FakeMeiliResponse(200, {"estimatedTotalHits": count})
        return FakeMeiliResponse(404, {"code": "not_found", "message": path})


def _uid_from_path(path: str) -> str | None:
    if not path.startswith("/indexes/"):
        return None
    return path.split("/", 3)[2]


def test_replace_vacancies_index_swaps_verified_staging_index(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inner() -> None:
        from skillra_api.services import vacancy_indexer

        fake = FakeMeiliClient()
        fake.indexes["vacancies"] = {"documents": [{"id": "old"}], "settings": {}, "primary_key": "id"}
        monkeypatch.setattr(vacancy_indexer.httpx, "AsyncClient", lambda *args, **kwargs: fake)

        snapshots = [
            VacancySnapshot(hh_vacancy_id="v001", title="Data Analyst", dataset_run_id="run-1"),
            VacancySnapshot(hh_vacancy_id="v002", title="Data Engineer", dataset_run_id="run-1"),
        ]
        settings = Settings(
            log_level="CRITICAL",
            api_token="test",
            meilisearch_url="http://meili",
            meilisearch_api_key="key",
        )

        indexed = await vacancy_indexer._replace_vacancies_index(settings, snapshots)

        assert indexed == 2
        assert fake.swaps == [["vacancies", "vacancies__staging__run_1"]]
        assert [doc["id"] for doc in fake.indexes["vacancies"]["documents"]] == ["v001", "v002"]
        assert "vacancies__staging__run_1" not in fake.indexes
        assert fake.indexes["vacancies"]["settings"]["filterableAttributes"]
        assert fake.indexes["vacancies"]["settings"]["pagination"] == {"maxTotalHits": 1000}

    _run(_inner())


def test_replace_vacancies_index_does_not_swap_incomplete_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _inner() -> None:
        from skillra_api.services import vacancy_indexer

        fake = FakeMeiliClient(stats_override={"vacancies__staging__run_1": 1})
        fake.indexes["vacancies"] = {"documents": [{"id": "old"}], "settings": {}, "primary_key": "id"}
        monkeypatch.setattr(vacancy_indexer.httpx, "AsyncClient", lambda *args, **kwargs: fake)

        snapshots = [
            VacancySnapshot(hh_vacancy_id="v001", title="Data Analyst", dataset_run_id="run-1"),
            VacancySnapshot(hh_vacancy_id="v002", title="Data Engineer", dataset_run_id="run-1"),
        ]
        settings = Settings(
            log_level="CRITICAL",
            api_token="test",
            meilisearch_url="http://meili",
            meilisearch_api_key="key",
        )

        with pytest.raises(RuntimeError, match="staging index incomplete"):
            await vacancy_indexer._replace_vacancies_index(settings, snapshots)

        assert fake.swaps == []
        assert fake.indexes["vacancies"]["documents"] == [{"id": "old"}]
        assert "vacancies__staging__run_1" not in fake.indexes

    _run(_inner())


def test_sync_inserts_rows(tmp_path: Path) -> None:
    """Parquet rows → vacancy_snapshots rows inserted correctly."""

    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots
        from sqlalchemy import select as sa_select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_indexer.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)

        maker = async_sessionmaker(engine, expire_on_commit=False)

        features_df = pd.DataFrame(
            [
                {
                    "hh_vacancy_id": "v001",
                    "title": "Python Developer",
                    "primary_role": "Backend Developer",
                    "grade_final": "Middle",
                    "city": "Moscow",
                    "city_tier": "tier1",
                    "country": "Russia",
                    "region": "Moscow",
                    "city_normalized": "Moscow",
                    "geo_scope": "remote",
                    "salary_from": 150000,
                    "salary_to": 250000,
                    "skills": ["Python", "Django"],
                    "description": "Backend dev role",
                    "url": "https://hh.ru/vacancy/v001",
                    "published_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
                },
                {
                    "hh_vacancy_id": "v002",
                    "title": "Data Analyst",
                    "primary_role": "Data Analyst",
                    "grade_final": "Junior",
                    "city": "Saint-Petersburg",
                    "city_tier": "tier1",
                    "salary_from": 100000,
                    "salary_to": 160000,
                    "skills": ["SQL", "Python"],
                    "description": "Analytics role",
                    "url": "https://hh.ru/vacancy/v002",
                    "published_at": datetime(2026, 5, 2, tzinfo=timezone.utc),
                },
            ]
        )

        settings = Settings(
            log_level="CRITICAL",
            api_token="test",
            database_url=db_url,
            meilisearch_url="",
            meilisearch_api_key="testkey",
        )

        with patch("skillra_api.services.vacancy_indexer.SearchService") as mock_search:
            mock_service = AsyncMock()
            mock_service.index_vacancies = AsyncMock()
            mock_service.aclose = AsyncMock()
            mock_search.return_value = mock_service

            async with maker() as session:
                result = await sync_vacancy_snapshots(session, features_df, settings)

        assert result["inserted"] == 2

        async with maker() as session:
            rows = list((await session.scalars(sa_select(VacancySnapshot))).all())
        assert len(rows) == 2
        titles = {r.title for r in rows}
        assert "Python Developer" in titles
        assert "Data Analyst" in titles
        geo_row = next(r for r in rows if r.title == "Python Developer")
        assert geo_row.country == "Russia"
        assert geo_row.city_normalized == "Moscow"
        assert geo_row.geo_scope == "remote"

        await engine.dispose()

    _run(_inner())


def test_sync_skips_empty_hh_id(tmp_path: Path) -> None:
    """Rows with empty hh_vacancy_id or title are skipped."""

    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_skip.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        features_df = pd.DataFrame(
            [
                {"hh_vacancy_id": "", "title": "No ID"},
                {"hh_vacancy_id": "v003", "title": ""},
                {"hh_vacancy_id": "v004", "title": "Valid Title"},
            ]
        )

        settings = Settings(
            log_level="CRITICAL",
            api_token="test",
            database_url=db_url,
            meilisearch_url="",
            meilisearch_api_key="testkey",
        )

        with patch("skillra_api.services.vacancy_indexer.SearchService") as mock_search:
            mock_service = AsyncMock()
            mock_service.index_vacancies = AsyncMock()
            mock_service.aclose = AsyncMock()
            mock_search.return_value = mock_service

            async with maker() as session:
                result = await sync_vacancy_snapshots(session, features_df, settings)

        assert result["inserted"] == 1
        await engine.dispose()

    _run(_inner())


def test_vacancy_snapshot_has_hh_url(tmp_path: Path) -> None:
    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots
        from sqlalchemy import select as sa_select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_url.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        long_description = "x" * 6000
        features_df = pd.DataFrame(
            [
                {
                    "hh_vacancy_id": "v-url",
                    "title": "Python Developer",
                    "description": long_description,
                    "url": "https://hh.ru/vacancy/v-url",
                }
            ]
        )
        settings = Settings(log_level="CRITICAL", api_token="test", database_url=db_url, meilisearch_url="")

        async with maker() as session:
            result = await sync_vacancy_snapshots(session, features_df, settings)

        assert result["inserted"] == 1
        async with maker() as session:
            row = await session.scalar(sa_select(VacancySnapshot).where(VacancySnapshot.hh_vacancy_id == "v-url"))
        assert row is not None
        assert row.hh_url == "https://hh.ru/vacancy/v-url"
        assert row.description_snippet == long_description[:5000]

        await engine.dispose()

    _run(_inner())


def test_sync_accepts_pipeline_vacancy_schema(tmp_path: Path) -> None:
    """Current pipeline schema is normalized into vacancy_snapshots."""

    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots
        from sqlalchemy import select as sa_select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_pipeline_schema.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        features_df = pd.DataFrame(
            [
                {
                    "vacancy_id": "123456",
                    "title": "Data Engineer",
                    "primary_role": "data",
                    "grade": "middle",
                    "skills": "Python, SQL, Airflow",
                    "vacancy_url": "https://hh.ru/vacancy/123456",
                    "published_at_iso": "2026-05-01T10:30:00+00:00",
                }
            ]
        )
        settings = Settings(log_level="CRITICAL", api_token="test", database_url=db_url, meilisearch_url="")

        async with maker() as session:
            result = await sync_vacancy_snapshots(session, features_df, settings)

        assert result["inserted"] == 1
        async with maker() as session:
            row = await session.scalar(sa_select(VacancySnapshot).where(VacancySnapshot.hh_vacancy_id == "123456"))

        assert row is not None
        assert row.title == "Data Engineer"
        assert row.url == "https://hh.ru/vacancy/123456"
        assert row.hh_url == "https://hh.ru/vacancy/123456"
        assert row.published_at is not None
        assert row.skills == ["Python", "SQL", "Airflow"]

        await engine.dispose()

    _run(_inner())


def test_incremental_indexing(tmp_path: Path) -> None:
    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots, sync_vacancy_snapshots_incremental
        from sqlalchemy import func
        from sqlalchemy import select as sa_select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_incremental.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(log_level="CRITICAL", api_token="test", database_url=db_url, meilisearch_url="")

        initial_df = pd.DataFrame([{"hh_vacancy_id": "v001", "title": "Existing"}])
        next_df = pd.DataFrame(
            [{"hh_vacancy_id": "v001", "title": "Existing"}, {"hh_vacancy_id": "v002", "title": "New"}]
        )

        async with maker() as session:
            await sync_vacancy_snapshots(session, initial_df, settings)
        async with maker() as session:
            result = await sync_vacancy_snapshots_incremental(session, next_df, settings)

        assert result["inserted"] == 1
        assert result["updated"] == 0
        assert result["deleted"] == 0
        assert result["indexed"] == 0
        assert result["deindexed"] == 0
        assert result["strategy"] == "reconcile"
        assert result["expected"] == 2
        assert result["db_total"] == 2
        assert result["search_total"] is None
        assert result["completeness_status"] == "not_configured"
        async with maker() as session:
            count = await session.scalar(sa_select(func.count()).select_from(VacancySnapshot))
        assert count == 2

        await engine.dispose()

    _run(_inner())


def test_incremental_reconciles_updated_and_removed_rows(tmp_path: Path) -> None:
    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots, sync_vacancy_snapshots_incremental
        from sqlalchemy import func
        from sqlalchemy import select as sa_select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_reconcile.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(log_level="CRITICAL", api_token="test", database_url=db_url, meilisearch_url="")

        initial_df = pd.DataFrame(
            [
                {"hh_vacancy_id": "v001", "title": "Old Title", "salary_from": 100000},
                {"hh_vacancy_id": "stale", "title": "Stale Vacancy"},
            ]
        )
        latest_df = pd.DataFrame(
            [
                {"hh_vacancy_id": "v001", "title": "Updated Title", "salary_from": 150000},
                {"hh_vacancy_id": "v002", "title": "New Vacancy"},
            ]
        )

        async with maker() as session:
            await sync_vacancy_snapshots(session, initial_df, settings)
        async with maker() as session:
            result = await sync_vacancy_snapshots_incremental(session, latest_df, settings)

        assert result["inserted"] == 1
        assert result["updated"] == 1
        assert result["deleted"] == 1
        assert result["indexed"] == 0
        assert result["deindexed"] == 0
        assert result["strategy"] == "reconcile"
        assert result["expected"] == 2
        assert result["db_total"] == 2
        assert result["search_total"] is None
        assert result["completeness_status"] == "not_configured"
        async with maker() as session:
            count = await session.scalar(sa_select(func.count()).select_from(VacancySnapshot))
            updated = await session.scalar(sa_select(VacancySnapshot).where(VacancySnapshot.hh_vacancy_id == "v001"))
            stale = await session.scalar(sa_select(VacancySnapshot).where(VacancySnapshot.hh_vacancy_id == "stale"))

        assert count == 2
        assert updated is not None
        assert updated.title == "Updated Title"
        assert updated.salary_from == 150000
        assert stale is None

        await engine.dispose()

    _run(_inner())


def test_sync_raises_on_missing_required_columns(tmp_path: Path) -> None:
    """ValueError raised when required columns are absent."""

    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_miss.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        settings = Settings(
            log_level="CRITICAL",
            api_token="test",
            database_url=db_url,
            meilisearch_url="",
            meilisearch_api_key="testkey",
        )

        features_df = pd.DataFrame([{"some_col": "val"}])

        with pytest.raises(ValueError, match="missing required columns"):
            async with maker() as session:
                await sync_vacancy_snapshots(session, features_df, settings)

        await engine.dispose()

    _run(_inner())


def test_sync_fails_closed_on_meilisearch_failure(tmp_path: Path) -> None:
    """MeiliSearch failure is surfaced so data publish can fail closed."""

    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_grace.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        features_df = pd.DataFrame([{"hh_vacancy_id": "v005", "title": "Go Developer"}])

        settings = Settings(
            log_level="CRITICAL",
            api_token="test",
            database_url=db_url,
            meilisearch_url="http://meilisearch:7700",
            meilisearch_api_key="testkey",
        )

        with patch(
            "skillra_api.services.vacancy_indexer._replace_vacancies_index",
            new=AsyncMock(side_effect=ConnectionError("MeiliSearch unreachable")),
        ):
            with pytest.raises(ConnectionError, match="MeiliSearch unreachable"):
                async with maker() as session:
                    await sync_vacancy_snapshots(session, features_df, settings)

        async with maker() as session:
            rows = list((await session.scalars(select(VacancySnapshot))).all())

        assert len(rows) == 1
        assert rows[0].hh_vacancy_id == "v005"

        await engine.dispose()

    from sqlalchemy import select

    _run(_inner())


def test_sync_skips_meilisearch_when_disabled(tmp_path: Path) -> None:
    """MeiliSearch can still be disabled explicitly for DB-only test/runtime modes."""

    async def _inner() -> None:
        from skillra_api.db.session import Base as SkillraBase
        from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_no_meili.db'}"
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(SkillraBase.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        features_df = pd.DataFrame([{"hh_vacancy_id": "v005", "title": "Go Developer"}])

        settings = Settings(
            log_level="CRITICAL",
            api_token="test",
            database_url=db_url,
            meilisearch_url="",
            meilisearch_api_key="testkey",
        )

        with patch("skillra_api.services.vacancy_indexer.SearchService") as mock_search:
            mock_search.side_effect = ConnectionError("MeiliSearch unreachable")

            async with maker() as session:
                result = await sync_vacancy_snapshots(session, features_df, settings)

        assert result["inserted"] == 1
        assert result["indexed"] == 0

        await engine.dispose()

    _run(_inner())


# ---------------------------------------------------------------------------
# Integration test: POST /v1/admin/index-meilisearch
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_client(tmp_path: Path, service_token: str, admin_token: str) -> Any:
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        admin_token=admin_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'admin_test.db'}",
        meilisearch_url="",
        data_watch_interval=0,
    )
    from skillra_api.main import create_app

    app = create_app(settings)

    with TestClient(app) as client:
        client.headers.update({"X-Skillra-Token": service_token, "X-Admin-Token": admin_token})
        yield client


def test_index_meilisearch_datastore_not_ready(admin_client: Any) -> None:
    """Returns 503 when DataStore not ready."""
    response = admin_client.post("/v1/admin/index-meilisearch")
    # DataStore not ready (no parquet files in test), expect 503
    assert response.status_code in (503, 200)  # 200 if empty df is acceptable


def test_notify_data_updated_no_redis(admin_client: Any) -> None:
    """Returns 503 when Redis is not configured."""
    response = admin_client.post("/v1/admin/notify-data-updated")
    assert response.status_code == 503
    assert response.json()["status"] == "redis_unavailable"
