from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.db import Base  # noqa: E402
from skillra_api.db.models import DigestHistory, ProductEvent, User  # noqa: E402
from skillra_api.main import create_app  # noqa: E402
from skillra_api.routers import digest as digest_router  # noqa: E402
from sqlalchemy import select


async def _prepare_database(app, engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture()
def digest_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"
    database_path = tmp_path / "digest.db"

    features_df = pd.DataFrame(
        {
            "primary_role": ["data", "data"],
            "grade_final": ["junior", "junior"],
            "city_tier": ["Moscow", "Moscow"],
            "work_mode": ["remote", "remote"],
            "salary_mid_rub_capped": [120_000, 150_000],
            "hh_vacancy_id": ["hh-feature-1", "hh-feature-2"],
            "title": ["Data Analyst new", "Junior Data Analyst"],
            "hh_url": ["https://example.test/vacancy/1", "https://example.test/vacancy/2"],
            "published_at": ["2026-05-20T10:00:00Z", "2026-05-18T10:00:00Z"],
            "is_remote": [True, True],
            "is_junior_friendly": [True, True],
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
            "work_mode": ["remote"],
            "domain": ["analytics"],
            "vacancy_count": [2],
            "salary_q25": [120_000],
            "salary_median": [135_000],
            "salary_q75": [150_000],
            "remote_share": [1.0],
            "junior_friendly_share": [1.0],
            "top_skills": [["sql", "python"]],
        }
    )
    market_view_df.to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    app = create_app(settings)
    engine = app.state.db_engine

    with TestClient(app) as client:
        client.portal.call(_prepare_database, app, engine)
        client.headers.update(auth_headers)
        yield client


def _profile_payload() -> dict[str, object]:
    return {
        "username": "digest_user",
        "target_role": "data",
        "target_grade": "junior",
        "target_city_tier": "Moscow",
        "target_work_mode": "remote",
        "target_domain": "analytics",
        "current_skills": ["python"],
    }


async def _add_digest_history(app, telegram_user_id: int, sent_at: datetime) -> None:
    async with app.state.session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        assert user is not None
        session.add(DigestHistory(user_id=user.id, sent_at=sent_at, format="HTML", text_preview="previous digest"))
        await session.commit()


async def _product_event_types(app, telegram_user_id: int) -> list[str]:
    async with app.state.session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        assert user is not None
        rows = await session.scalars(select(ProductEvent.event_type).where(ProductEvent.user_id == user.id))
        return list(rows.all())


def test_digest_preview_includes_analytics(digest_client: TestClient) -> None:
    put_response = digest_client.put("/v1/users/300/profile", json=_profile_payload())
    assert put_response.status_code == 200

    response = digest_client.post("/v1/users/300/digest-preview")
    assert response.status_code == 200

    body = response.json()
    assert body["format"] == "HTML"
    text = body["text"]

    assert "Skillra Weekly Digest" in text
    assert "Вакансии: 2" in text
    assert "Зарплаты" in text
    assert "sql" in text
    assert "python" in text


def test_digest_preview_accepts_matching_user_api_key(digest_client: TestClient) -> None:
    put_response = digest_client.put("/v1/users/303/profile", json=_profile_payload())
    assert put_response.status_code == 200
    created_key = digest_client.post("/v1/users/303/api-key")
    assert created_key.status_code == 200
    user_key = created_key.json()["key"]

    service_token = digest_client.headers.pop("X-Skillra-Token", None)
    try:
        response = digest_client.post(
            "/v1/users/303/digest-preview?source=web",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        forbidden = digest_client.post(
            "/v1/users/304/digest-preview?source=web",
            headers={"Authorization": f"Bearer {user_key}"},
        )
    finally:
        if service_token is not None:
            digest_client.headers["X-Skillra-Token"] = service_token

    assert response.status_code == 200
    assert response.json()["text"]
    assert forbidden.status_code == 403


def test_digest_preview_includes_career_plan_actions(digest_client: TestClient) -> None:
    put_response = digest_client.put("/v1/users/301/profile", json=_profile_payload())
    assert put_response.status_code == 200

    plan_response = digest_client.put("/v1/users/301/career-plan", json={"notes": "digest plan"})
    assert plan_response.status_code == 200
    done_action = digest_client.post(
        "/v1/users/301/career-plan/actions",
        json={"title": "Finish SQL module", "status": "done", "priority": 10},
    )
    assert done_action.status_code == 200
    planned_action = digest_client.post(
        "/v1/users/301/career-plan/actions",
        json={"title": "Prepare portfolio project", "status": "planned", "priority": 20},
    )
    assert planned_action.status_code == 200
    saved_vacancy = digest_client.post(
        "/v1/users/301/career-plan/saved-vacancies",
        json={"hh_vacancy_id": "hh-301", "title": "Data Analyst"},
    )
    assert saved_vacancy.status_code == 200

    response = digest_client.post("/v1/users/301/digest-preview")

    assert response.status_code == 200
    text = response.json()["text"]
    assert "Карьерный план" in text
    assert "Прогресс: 1/3" in text
    assert "Prepare portfolio project" in text
    assert "Data Analyst" in text
    assert "Finish SQL module" not in text


def test_digest_preview_includes_adaptive_sections(digest_client: TestClient) -> None:
    put_response = digest_client.put("/v1/users/302/profile", json=_profile_payload())
    assert put_response.status_code == 200
    digest_client.portal.call(
        _add_digest_history,
        digest_client.app,
        302,
        datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc),
    )
    plan_response = digest_client.put("/v1/users/302/career-plan", json={"notes": "digest plan"})
    assert plan_response.status_code == 200
    stale_action = digest_client.post(
        "/v1/users/302/career-plan/actions",
        json={"title": "Finish SQL portfolio", "status": "planned", "priority": 20, "due_date": "2020-01-01"},
    )
    assert stale_action.status_code == 200
    saved_vacancy = digest_client.post(
        "/v1/users/302/career-plan/saved-vacancies",
        json={"hh_vacancy_id": "hh-302", "title": "Data Analyst"},
    )
    assert saved_vacancy.status_code == 200
    outcome = digest_client.post(
        f"/v1/users/302/career-plan/actions/{saved_vacancy.json()['id']}/outcome",
        json={"status": "applied", "source": "user"},
    )
    assert outcome.status_code == 200

    response = digest_client.post("/v1/users/302/digest-preview")

    assert response.status_code == 200
    text = response.json()["text"]
    assert "Изменения с прошлого дайджеста" in text
    assert "вакансия сохранена" in text
    assert "Отклики" in text
    assert "Data Analyst — отклик" in text
    assert "Новые вакансии по профилю" in text
    assert "Data Analyst new" in text
    assert "Зависшие действия" in text
    assert "Finish SQL portfolio" in text
    assert "Обновить план" in text
    event_types = digest_client.portal.call(_product_event_types, digest_client.app, 302)
    assert "digest_preview_viewed" in event_types
    assert "digest_engagement" in event_types
    assert "weekly_returned" in event_types
    assert "weekly_return" in event_types


def test_digest_chart_returns_png(digest_client: TestClient) -> None:
    put_response = digest_client.put("/v1/users/300/profile", json=_profile_payload())
    assert put_response.status_code == 200

    response = digest_client.get("/v1/users/300/digest-chart")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content


def test_digest_chart_handles_unavailable(monkeypatch: pytest.MonkeyPatch, digest_client: TestClient) -> None:
    put_response = digest_client.put("/v1/users/300/profile", json=_profile_payload())
    assert put_response.status_code == 200

    def raise_unavailable(*_args, **_kwargs):
        raise ValueError("gap unavailable")

    monkeypatch.setattr(digest_router, "plot_persona_skill_gap", raise_unavailable)

    response = digest_client.get("/v1/users/300/digest-chart")

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "PERSONA_SKILL_GAP_UNAVAILABLE"


def test_digest_preview_matches_schema(digest_client: TestClient) -> None:
    put_response = digest_client.put("/v1/users/300/profile", json=_profile_payload())
    assert put_response.status_code == 200

    response = digest_client.post("/v1/users/300/digest-preview")

    assert response.status_code == 200
    body = response.json()
    assert {"format", "text"}.issubset(body)
    assert isinstance(body["format"], str)
    assert isinstance(body["text"], str)
    assert body["text"]
