from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings
from skillra_api.db import Base
from skillra_api.db.models import CareerAction, CareerPlan, ProductEvent, User, UserProfile, VacancySnapshot
from skillra_api.main import create_app
from skillra_api.routers import search as search_router
from skillra_api.services.search import (
    VACANCY_FILTERABLE_ATTRIBUTES,
    VACANCY_SEARCHABLE_ATTRIBUTES,
    VACANCY_SORTABLE_ATTRIBUTES,
    SearchService,
    configure_search_indexes,
)
from sqlalchemy import select


async def _prepare_database(app, snapshot: VacancySnapshot) -> None:
    engine = app.state.db_engine
    session_maker = app.state.session_maker
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_maker() as session:
        session.add(snapshot)
        await session.commit()


async def _prepare_match_context(app, telegram_user_id: int) -> None:
    session_maker = app.state.session_maker
    async with session_maker() as session:
        user = User(telegram_user_id=telegram_user_id)
        user.profile = UserProfile(
            target_role="data",
            target_grade="junior",
            target_city="Moscow",
            target_work_mode="remote",
            current_skills=["python"],
        )
        user.career_plan = CareerPlan(
            target_role="data",
            target_grade="junior",
            target_city="Moscow",
            target_work_mode="remote",
            status="active",
            actions=[
                CareerAction(
                    title="Close SQL gap",
                    action_type="learning",
                    status="planned",
                    priority=10,
                    skill_name="sql",
                )
            ],
        )
        session.add(user)
        await session.commit()


async def _product_events(app, telegram_user_id: int) -> list[ProductEvent]:
    session_maker = app.state.session_maker
    async with session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        assert user is not None
        rows = await session.scalars(
            select(ProductEvent).where(ProductEvent.user_id == user.id).order_by(ProductEvent.id)
        )
        return list(rows.all())


@pytest.fixture()
def search_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'search.db'}",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    snapshot = VacancySnapshot(
        hh_vacancy_id="123",
        title="Python Data Analyst",
        primary_role="data",
        grade="junior",
        city="Moscow",
        skills=["python", "sql"],
        description_snippet="Analytics and SQL",
    )
    with TestClient(app) as client:
        client.portal.call(_prepare_database, app, snapshot)
        client.headers.update(auth_headers)
        yield client


@pytest.fixture()
def skill_search_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "features.parquet"
    market_view_path = tmp_path / "market.parquet"
    pd = pytest.importorskip("pandas")
    pd.DataFrame({"skill_python": [True], "has_sql": [True], "skill_go": [False]}).to_parquet(features_path)
    pd.DataFrame({"primary_role": ["data"], "grade_final": ["junior"], "city_tier": ["Moscow"]}).to_parquet(
        market_view_path
    )
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        database_url="",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update(auth_headers)
        yield client


def test_search_service_builds_meili_filter() -> None:
    assert (
        SearchService._build_filter({"primary_role": "data", "grade": "junior", "skills": "python"})
        == 'primary_role = "data" AND grade = "junior" AND skills = "python"'
    )
    assert SearchService._build_filter({"primary_role": None}) is None


def test_configure_search_indexes_sets_filterable_and_searchable_attributes() -> None:
    class FakeIndex:
        def __init__(self) -> None:
            self.searchable: list[str] | None = None
            self.filterable: list[str] | None = None
            self.sortable: list[str] | None = None

        async def update_searchable_attributes(self, values: list[str]) -> None:
            self.searchable = values

        async def update_filterable_attributes(self, values: list[str]) -> None:
            self.filterable = values

        async def update_sortable_attributes(self, values: list[str]) -> None:
            self.sortable = values

    class FakeClient:
        def __init__(self) -> None:
            self.indexes = {"vacancies": FakeIndex(), "skills": FakeIndex()}

        async def get_index(self, name: str) -> FakeIndex:
            return self.indexes[name]

    client = FakeClient()

    asyncio.get_event_loop().run_until_complete(configure_search_indexes(client))

    vacancies = client.indexes["vacancies"]
    skills = client.indexes["skills"]
    assert vacancies.searchable == VACANCY_SEARCHABLE_ATTRIBUTES
    assert vacancies.filterable == VACANCY_FILTERABLE_ATTRIBUTES
    assert vacancies.sortable == VACANCY_SORTABLE_ATTRIBUTES
    assert skills.searchable == ["name", "skill"]


def test_search_service_serializes_vacancy_snapshot() -> None:
    published_at = datetime(2026, 5, 18, tzinfo=timezone.utc)
    snapshot = VacancySnapshot(
        hh_vacancy_id="123",
        title="Data Analyst",
        primary_role="data",
        grade="junior",
        city="Moscow",
        city_tier="Tier-1",
        salary_from=100000,
        salary_to=150000,
        skills=["python", "sql"],
        description_snippet="Analytics role",
        url="https://example.test/123",
        published_at=published_at,
    )

    document = SearchService._to_document(snapshot)

    assert document["id"] == "123"
    assert document["skills"] == ["python", "sql"]
    assert document["published_at"] == "2026-05-18T00:00:00+00:00"


def test_index_vacancies_creates_missing_meili_index() -> None:
    class MissingIndexError(Exception):
        pass

    class FakeIndex:
        def __init__(self) -> None:
            self.documents: list[dict[str, object]] = []
            self.searchable: list[str] | None = None
            self.filterable: list[str] | None = None
            self.sortable: list[str] | None = None

        async def add_documents(self, documents: list[dict[str, object]]) -> None:
            self.documents.extend(documents)

        async def update_searchable_attributes(self, values: list[str]) -> None:
            self.searchable = values

        async def update_filterable_attributes(self, values: list[str]) -> None:
            self.filterable = values

        async def update_sortable_attributes(self, values: list[str]) -> None:
            self.sortable = values

    class FakeClient:
        def __init__(self) -> None:
            self.indexes: dict[str, FakeIndex] = {}
            self.created: list[tuple[str, str]] = []

        async def get_index(self, name: str) -> FakeIndex:
            if name not in self.indexes:
                raise MissingIndexError(f"MeilisearchApiError.index_not_found Index `{name}` not found")
            return self.indexes[name]

        async def create_index_if_not_exists(self, name: str, *, primary_key: str) -> None:
            self.created.append((name, primary_key))
            self.indexes[name] = FakeIndex()

    client = FakeClient()
    service = SearchService(client=client)
    snapshot = VacancySnapshot(hh_vacancy_id="123", title="Python Developer")

    asyncio.get_event_loop().run_until_complete(service.index_vacancies([snapshot]))

    assert client.created == [("vacancies", "id")]
    vacancies = client.indexes["vacancies"]
    assert vacancies.documents[0]["id"] == "123"
    assert vacancies.searchable == VACANCY_SEARCHABLE_ATTRIBUTES
    assert vacancies.filterable == VACANCY_FILTERABLE_ATTRIBUTES
    assert vacancies.sortable == VACANCY_SORTABLE_ATTRIBUTES


def test_count_vacancies_updates_existing_meili_settings_before_filter() -> None:
    class FakeIndex:
        def __init__(self) -> None:
            self.searchable: list[str] | None = None
            self.filterable: list[str] | None = None
            self.sortable: list[str] | None = None
            self.search_filter: str | None = None

        async def update_searchable_attributes(self, values: list[str]) -> None:
            self.searchable = values

        async def update_filterable_attributes(self, values: list[str]) -> None:
            self.filterable = values

        async def update_sortable_attributes(self, values: list[str]) -> None:
            self.sortable = values

        async def search(self, query: str, *, limit: int, filter: str | None) -> dict[str, object]:
            assert query == ""
            assert limit == 0
            assert self.filterable is not None
            assert "dataset_run_id" in self.filterable
            self.search_filter = filter
            return {"estimatedTotalHits": 7}

    class FakeClient:
        def __init__(self) -> None:
            self.index = FakeIndex()

        async def get_index(self, name: str) -> FakeIndex:
            assert name == "vacancies"
            return self.index

    client = FakeClient()
    service = SearchService(client=client)

    result = asyncio.get_event_loop().run_until_complete(service.count_vacancies(dataset_run_id="run-1"))

    assert result == 7
    assert client.index.searchable == VACANCY_SEARCHABLE_ATTRIBUTES
    assert client.index.filterable == VACANCY_FILTERABLE_ATTRIBUTES
    assert client.index.sortable == VACANCY_SORTABLE_ATTRIBUTES
    assert client.index.search_filter == 'dataset_run_id = "run-1"'


def test_vacancy_search_uses_database_fallback(search_client: TestClient) -> None:
    response = search_client.get("/v1/search/vacancies", params={"q": "python", "role": "data"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["results"][0]["hh_vacancy_id"] == "123"
    assert body["index_status"] == "idle"
    assert body["search_state"] == "fallback"
    assert body["degraded_reason"] == "MeiliSearch недоступен, результаты возвращены из базы вакансий."
    assert body["confidence"] == "low"
    assert body["warnings"] == [
        "Search index has not been built yet.",
        "MeiliSearch is unavailable; returned DB fallback results.",
    ]


def test_vacancy_search_adds_profile_match_explanations(search_client: TestClient) -> None:
    search_client.portal.call(_prepare_match_context, search_client.app, 77)

    response = search_client.get(
        "/v1/search/vacancies",
        params={"q": "python", "role": "data", "telegram_user_id": 77, "source": "web"},
    )

    assert response.status_code == 200
    body = response.json()
    result = body["results"][0]
    assert result["match_level"] == "high"
    assert result["match_score"] >= 75
    assert result["matched_skills"] == ["python"]
    assert result["missing_skills"] == ["sql"]
    assert "роль совпадает" in result["fit_reason"]
    assert "нужно подтянуть: sql" in result["gap_reason"]
    assert "Close SQL gap" in result["plan_relevance"]
    assert any("формат работы" in warning for warning in body["warnings"])
    events = search_client.portal.call(_product_events, search_client.app, 77)
    assert [event.event_type for event in events] == [
        "vacancy_search_performed",
        "vacancy_match_explained",
        "search_degraded_warning_shown",
    ]
    assert events[0].source == "web"
    assert events[0].payload["query_length"] == len("python")
    assert events[0].payload["trust_tier"] == "degraded_search"


def test_search_skills_fallback(skill_search_client: TestClient) -> None:
    response = skill_search_client.get("/v1/search/skills", params={"q": "py"})

    assert response.status_code == 200
    body = response.json()
    assert body["skills"] == ["python"]
    assert body["total"] == 1


def test_search_skills_falls_back_when_meili_index_is_empty(skill_search_client: TestClient) -> None:
    class EmptySkillSearchService:
        async def search_skills(self, query: str, *, limit: int = 10) -> SimpleNamespace:
            return SimpleNamespace(hits=[], estimated_total_hits=0)

    skill_search_client.app.dependency_overrides[search_router._get_search_service] = EmptySkillSearchService
    try:
        response = skill_search_client.get("/v1/search/skills", params={"q": "py"})
    finally:
        skill_search_client.app.dependency_overrides.pop(search_router._get_search_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["skills"] == ["python"]
    assert body["total"] == 1
