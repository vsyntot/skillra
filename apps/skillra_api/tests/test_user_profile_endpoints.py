from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.db import Base  # noqa: E402
from skillra_api.db.models import ProductEvent, User, UserCommercialAccount  # noqa: E402
from skillra_api.main import create_app  # noqa: E402
from skillra_api.services.commercial import entitlements_for_plan
from sqlalchemy import select


async def _prepare_database(app, engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _set_commercial_plan(app, telegram_user_id: int, plan: str = "pro") -> None:
    async with app.state.session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        assert user is not None
        account = await session.scalar(select(UserCommercialAccount).where(UserCommercialAccount.user_id == user.id))
        if account is None:
            account = UserCommercialAccount(user_id=user.id)
            session.add(account)
        account.plan = plan
        account.subscription_state = "active" if plan in {"pro", "admin"} else "trialing"
        account.entitlements = entitlements_for_plan(plan)
        await session.commit()


@pytest.fixture()
def profile_client(
    tmp_path: Path, service_token: str, admin_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"
    database_path = tmp_path / "profiles.db"

    features_df = pd.DataFrame(
        {
            "primary_role": ["data"],
            "grade_final": ["junior"],
            "city_tier": ["Moscow"],
            "country": ["Russia"],
            "region": ["Moscow"],
            "city_normalized": ["Moscow"],
            "geo_scope": ["remote"],
            "work_mode": ["remote"],
            "skill_python": [True],
        }
    )
    features_df.to_parquet(features_path)

    market_view_df = pd.DataFrame(
        {
            "primary_role": ["data"],
            "city_tier": ["Moscow"],
            "country": ["Russia"],
            "region": ["Moscow"],
            "city_normalized": ["Moscow"],
            "geo_scope": ["remote"],
            "grade_final": ["junior"],
            "vacancy_count": [1],
        }
    )
    market_view_df.to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        api_token=service_token,
        admin_token=admin_token,
        database_url=f"sqlite+aiosqlite:///{database_path}",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    engine = app.state.db_engine

    with TestClient(app) as client:
        client.portal.call(_prepare_database, app, engine)
        client.headers.update(auth_headers)
        yield client


@pytest.fixture()
def profile_client_no_meta(
    tmp_path: Path, service_token: str, admin_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "profiles_no_meta.db"
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        admin_token=admin_token,
        database_url=f"sqlite+aiosqlite:///{database_path}",
        meilisearch_url="",
        data_watch_interval=0,
    )
    app = create_app(settings)
    engine = app.state.db_engine

    with TestClient(app) as client:
        client.portal.call(_prepare_database, app, engine)
        client.headers.update(auth_headers)
        yield client


def _profile_payload() -> dict[str, object]:
    return {
        "username": "test_user",
        "target_role": "data",
        "target_grade": "junior",
        "target_city_tier": "Moscow",
        "target_country": "Russia",
        "target_region": "Moscow",
        "target_city": "Moscow",
        "target_geo_scope": "remote",
        "target_work_mode": "remote",
        "target_domain": "analytics",
        "current_skills": ["python"],
    }


async def _add_product_event(
    app,
    telegram_user_id: int,
    event_type: str,
    source: str,
    payload: dict[str, object] | None = None,
) -> None:
    from skillra_api.db.models import User  # noqa: PLC0415

    async with app.state.session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        assert user is not None
        session.add(
            ProductEvent(
                user_id=user.id,
                event_type=event_type,
                source=source,
                entity_type="test",
                payload=payload,
                occurred_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


def test_upsert_get_delete_profile(profile_client: TestClient) -> None:
    put_response = profile_client.put("/v1/users/100/profile", json=_profile_payload())
    assert put_response.status_code == 200
    created_profile = put_response.json()
    assert created_profile["telegram_user_id"] == 100
    assert created_profile["current_skills"] == ["python"]
    assert created_profile["warnings"] == []

    get_response = profile_client.get("/v1/users/100/profile")
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["target_role"] == "data"
    assert fetched["target_city"] == "Moscow"
    assert fetched["target_geo_scope"] == "remote"
    assert fetched["current_skills"] == ["python"]

    delete_response = profile_client.delete("/v1/users/100/profile")
    assert delete_response.status_code == 204

    missing_response = profile_client.get("/v1/users/100/profile")
    assert missing_response.status_code == 404
    assert missing_response.json()["error_code"] == "PROFILE_NOT_FOUND"


def test_profile_rejects_unknown_skills(profile_client: TestClient) -> None:
    payload = _profile_payload()
    payload["current_skills"] = ["unknown"]

    response = profile_client.put("/v1/users/101/profile", json=payload)
    assert response.status_code == 400
    assert response.json()["error_code"] == "UNKNOWN_SKILLS"


def test_upsert_profile_invalid_role_returns_422(profile_client: TestClient) -> None:
    payload = _profile_payload()
    payload["target_role"] = "backend"

    response = profile_client.put("/v1/users/102/profile", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_META_VALUE"


def test_upsert_profile_valid_role_ok(profile_client: TestClient) -> None:
    response = profile_client.put("/v1/users/103/profile", json=_profile_payload())

    assert response.status_code == 200
    assert response.json()["target_role"] == "data"


def test_profile_allows_skills_without_meta(profile_client_no_meta: TestClient) -> None:
    payload = _profile_payload()
    payload["current_skills"] = ["anything"]

    response = profile_client_no_meta.put("/v1/users/200/profile", json=payload)
    assert response.status_code == 200
    assert response.json()["warnings"]


def test_user_api_key_flow_allows_users_me(profile_client: TestClient) -> None:
    profile_client.put("/v1/users/300/profile", json=_profile_payload())

    created = profile_client.post("/v1/users/300/api-key")
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["key"].startswith("sk_300_")
    assert created_body["key_prefix"] == created_body["key"][:8]

    status = profile_client.get("/v1/users/300/api-key")
    assert status.status_code == 200
    assert status.json()["is_active"] is True

    me = profile_client.get("/v1/users/me", headers={"X-Skillra-Token": created_body["key"]})
    assert me.status_code == 200
    assert me.json()["telegram_user_id"] == 300
    assert me.json()["profile"]["target_role"] == "data"

    self_status = profile_client.get("/v1/users/me/api-key", headers={"X-Skillra-Token": created_body["key"]})
    assert self_status.status_code == 200
    assert self_status.json()["key_prefix"] == created_body["key_prefix"]

    self_revoked = profile_client.delete(
        "/v1/users/me/api-key",
        headers={"X-Skillra-Token": created_body["key"]},
        params={"source": "web"},
    )
    assert self_revoked.status_code == 200
    assert self_revoked.json()["revoked"] is True

    rejected = profile_client.get("/v1/users/me", headers={"X-Skillra-Token": created_body["key"]})
    assert rejected.status_code == 401

    created_again = profile_client.post("/v1/users/300/api-key").json()
    revoked = profile_client.delete("/v1/users/300/api-key")
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True

    rejected = profile_client.get("/v1/users/me", headers={"X-Skillra-Token": created_again["key"]})
    assert rejected.status_code == 401


def test_users_me_rejects_service_token_without_user(profile_client: TestClient) -> None:
    response = profile_client.get("/v1/users/me")

    assert response.status_code == 403


def test_user_api_key_can_read_meta_and_only_own_profile(profile_client: TestClient) -> None:
    profile_client.put("/v1/users/301/profile", json=_profile_payload())
    created = profile_client.post("/v1/users/301/api-key").json()
    user_headers = {"X-Skillra-Token": created["key"]}

    meta = profile_client.get("/v1/meta/roles", headers=user_headers)
    assert meta.status_code == 200

    own_profile = profile_client.get("/v1/users/301/profile", headers=user_headers)
    assert own_profile.status_code == 200

    other_profile = profile_client.get("/v1/users/302/profile", headers=user_headers)
    assert other_profile.status_code == 403
    assert other_profile.json()["error_code"] == "USER_SCOPE_FORBIDDEN"


def test_next_best_action_guides_missing_profile(profile_client: TestClient) -> None:
    response = profile_client.get("/v1/users/340/next-best-action", params={"source": "web"})

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "create_profile"
    assert body["route"] == "/profile"
    assert body["command"] == "/profile"
    assert body["profile_quality"]["score"] == 0


def test_next_best_action_guides_incomplete_profile(profile_client: TestClient) -> None:
    response = profile_client.put(
        "/v1/users/341/profile",
        json={"target_role": "data", "current_skills": [], "source": "web"},
    )
    assert response.status_code == 200

    action = profile_client.get("/v1/users/341/next-best-action", params={"source": "web"}).json()

    assert action["state"] == "complete_profile"
    assert action["profile_quality"]["score"] < 100
    assert "target_grade" in action["profile_quality"]["missing_fields"]


def test_next_best_action_guides_plan_creation(profile_client: TestClient) -> None:
    profile_client.put("/v1/users/342/profile", json={**_profile_payload(), "source": "web"})

    action = profile_client.get("/v1/users/342/next-best-action", params={"source": "web"}).json()

    assert action["state"] == "create_plan"
    assert action["route"] == "/career-plan"
    assert action["profile_quality"]["is_complete"] is True


def test_next_best_action_guides_action_generation_and_vacancy_search(profile_client: TestClient) -> None:
    profile_client.put("/v1/users/343/profile", json={**_profile_payload(), "source": "web"})
    profile_client.put("/v1/users/343/career-plan", json={})

    empty_plan_action = profile_client.get("/v1/users/343/next-best-action", params={"source": "web"}).json()
    assert empty_plan_action["state"] == "generate_plan_actions"

    profile_client.post(
        "/v1/users/343/career-plan/actions",
        json={"title": "Close SQL gap", "action_type": "learning", "status": "planned", "source": "web"},
    )
    vacancy_action = profile_client.get("/v1/users/343/next-best-action", params={"source": "web"}).json()

    assert vacancy_action["state"] == "find_vacancy"
    assert vacancy_action["route"] == "/search"


def test_next_best_action_guides_application_outcome_and_active_user(profile_client: TestClient) -> None:
    profile_client.put("/v1/users/344/profile", json={**_profile_payload(), "source": "web"})
    profile_client.put("/v1/users/344/career-plan", json={})
    profile_client.post(
        "/v1/users/344/career-plan/actions",
        json={"title": "Ship a portfolio case", "action_type": "portfolio", "status": "planned", "source": "web"},
    )
    saved = profile_client.post(
        "/v1/users/344/career-plan/saved-vacancies",
        json={"hh_vacancy_id": "344", "title": "Data Analyst", "url": "https://hh.ru/vacancy/344", "source": "web"},
    ).json()

    update_action = profile_client.get("/v1/users/344/next-best-action", params={"source": "bot"}).json()
    assert update_action["state"] == "update_application_outcome"

    profile_client.post(
        f"/v1/users/344/career-plan/actions/{saved['id']}/outcome",
        json={"status": "applied", "source": "web"},
    )
    digest_action = profile_client.get("/v1/users/344/next-best-action", params={"source": "bot"}).json()
    assert digest_action["state"] == "enable_digest"

    profile_client.put(
        "/v1/users/344/subscriptions/weekly",
        json={"active": True, "weekday": 0, "time_local": "09:00", "timezone": "Europe/Moscow"},
    )
    active_action = profile_client.get("/v1/users/344/next-best-action", params={"source": "web"}).json()
    assert active_action["state"] == "continue_plan"
    assert active_action["title"] == "Ship a portfolio case"


def test_next_best_action_reports_stale_dataset_warning(profile_client: TestClient) -> None:
    datastore = profile_client.app.state.datastore
    with datastore._lock:  # noqa: SLF001 - test-only injection of dataset metadata
        datastore._dataset_meta = {"generated_at_utc": "2025-01-01T00:00:00+00:00"}  # noqa: SLF001

    response = profile_client.get("/v1/users/345/next-best-action")

    assert response.status_code == 200
    assert "старше 30 дней" in response.json()["trust_warning"]


def test_evidence_packet_and_flagged_explainer(profile_client: TestClient) -> None:
    payload = _profile_payload()
    profile_client.put("/v1/users/347/profile", json={**payload, "source": "web"})

    datastore = profile_client.app.state.datastore
    with datastore._lock:  # noqa: SLF001 - test-only injection of dataset metadata
        datastore._dataset_meta = {  # noqa: SLF001
            "run_id": "run-038",
            "generated_at_utc": "2026-05-27T00:00:00+00:00",
            "date_semantics_status": "passed",
            "product_eligibility": {
                "search": {"eligible": True},
                "salary": {"eligible": True},
                "trends": {"eligible": True},
                "recommendations": {"eligible": True},
            },
        }

    packet = profile_client.get("/v1/users/347/evidence-packet", params={"task": "skill_gap_explanation"})
    assert packet.status_code == 200
    packet_body = packet.json()
    assert packet_body["version"] == "evidence_packet.v1"
    assert packet_body["dataset"]["dataset_run_id"] == "run-038"
    assert any(item["evidence_type"] == "market_summary" for item in packet_body["evidence"])

    disabled = profile_client.get("/v1/users/347/evidence-explainer", params={"task": "skill_gap_explanation"})
    assert disabled.status_code == 404
    assert disabled.json()["error_code"] == "EVIDENCE_EXPLAINER_DISABLED"

    profile_client.app.state.settings.evidence_explainer_enabled = True
    enabled = profile_client.get("/v1/users/347/evidence-explainer", params={"task": "skill_gap_explanation"})
    assert enabled.status_code == 200
    body = enabled.json()
    assert body["status"] == "fallback"
    assert body["evidence_refs"]
    assert {ref["evidence_id"] for ref in body["evidence_refs"]}.issubset(
        {item["evidence_id"] for item in packet_body["evidence"]}
    )
    metrics = profile_client.get("/internal/metrics")
    assert metrics.status_code == 200
    assert (
        'skillra_evidence_explainer_requests_total{runtime_env="local",'
        'status="fallback",surface="web",task="skill_gap_explanation"}'
    ) in metrics.text
    evidence_metric_lines = "\n".join(
        line for line in metrics.text.splitlines() if line.startswith("skillra_evidence_explainer_")
    )
    assert "telegram_user_id" not in evidence_metric_lines


def test_evidence_explainer_requires_allowlist_in_staging(profile_client: TestClient) -> None:
    payload = _profile_payload()
    profile_client.put("/v1/users/348/profile", json={**payload, "source": "web"})
    profile_client.app.state.settings.runtime_env = "staging"
    profile_client.app.state.settings.evidence_explainer_enabled = True

    no_allowlist = profile_client.get("/v1/users/348/evidence-explainer", params={"task": "skill_gap_explanation"})
    profile_client.app.state.settings.evidence_explainer_allowed_telegram_user_ids = "999"
    not_allowed = profile_client.get("/v1/users/348/evidence-explainer", params={"task": "skill_gap_explanation"})
    profile_client.app.state.settings.evidence_explainer_allowed_telegram_user_ids = "348,999"
    allowed = profile_client.get("/v1/users/348/evidence-explainer", params={"task": "skill_gap_explanation"})

    assert no_allowlist.status_code == 404
    assert no_allowlist.json()["details"]["reason"] == "staging_allowlist_required"
    assert not_allowed.status_code == 403
    assert not_allowed.json()["error_code"] == "EVIDENCE_EXPLAINER_NOT_ALLOWED"
    assert allowed.status_code == 200


def test_evidence_explainer_prod_requires_explicit_approval_and_allowlist(profile_client: TestClient) -> None:
    payload = _profile_payload()
    profile_client.put("/v1/users/349/profile", json={**payload, "source": "web"})
    profile_client.app.state.settings.runtime_env = "prod"
    profile_client.app.state.settings.evidence_explainer_enabled = True
    profile_client.app.state.settings.evidence_explainer_allowed_telegram_user_ids = "349"

    blocked = profile_client.get("/v1/users/349/evidence-explainer", params={"task": "skill_gap_explanation"})
    profile_client.app.state.settings.evidence_explainer_prod_enable_approved = True
    allowed = profile_client.get("/v1/users/349/evidence-explainer", params={"task": "skill_gap_explanation"})

    assert blocked.status_code == 404
    assert blocked.json()["details"]["reason"] == "prod_not_approved"
    assert allowed.status_code == 200


def test_next_best_action_events_feed_activation_summary(
    profile_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    profile_client.put("/v1/users/346/profile", json={**_profile_payload(), "source": "web"})
    profile_client.put("/v1/users/346/career-plan", json={})
    profile_client.post(
        "/v1/users/346/career-plan/actions",
        json={"title": "Close SQL gap", "action_type": "learning", "status": "planned", "source": "web"},
    )

    assert profile_client.get("/v1/users/346/next-best-action", params={"source": "web"}).status_code == 200
    action = profile_client.get("/v1/users/346/next-best-action", params={"source": "bot"}).json()
    assert action["state"] == "find_vacancy"

    response = profile_client.get("/v1/admin/product-loop-summary?days=30", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["activation_events_by_source"]["web"] == 2
    assert body["activation_events_by_source"]["bot"] == 1
    assert body["first_value_users_by_source"]["bot"] == 1


def test_career_plan_lifecycle_and_saved_vacancy(profile_client: TestClient) -> None:
    profile_client.put("/v1/users/350/profile", json=_profile_payload())

    created_plan = profile_client.put("/v1/users/350/career-plan", json={"notes": "baseline"})
    assert created_plan.status_code == 200
    plan_body = created_plan.json()
    assert plan_body["target_role"] == "data"
    assert plan_body["status"] == "active"
    assert plan_body["actions"] == []

    created_action = profile_client.post(
        "/v1/users/350/career-plan/actions",
        json={
            "title": "Learn Airflow",
            "action_type": "learning",
            "skill_name": "airflow",
            "priority": 10,
        },
    )
    assert created_action.status_code == 200
    action_body = created_action.json()
    assert action_body["status"] == "planned"

    completed_action = profile_client.patch(
        f"/v1/users/350/career-plan/actions/{action_body['id']}",
        json={"status": "done"},
    )
    assert completed_action.status_code == 200
    assert completed_action.json()["completed_at"]

    saved_vacancy = profile_client.post(
        "/v1/users/350/career-plan/saved-vacancies",
        json={"hh_vacancy_id": "123", "title": "Data Analyst", "url": "https://hh.ru/vacancy/123"},
    )
    assert saved_vacancy.status_code == 200
    assert saved_vacancy.json()["action_type"] == "saved_vacancy"
    assert saved_vacancy.json()["hh_vacancy_id"] == "123"
    assert saved_vacancy.json()["application_status"] == "saved"

    duplicate_vacancy = profile_client.post(
        "/v1/users/350/career-plan/saved-vacancies",
        json={
            "hh_vacancy_id": "123",
            "title": "Data Analyst updated",
            "url": "https://hh.ru/vacancy/123?from=search",
        },
    )
    assert duplicate_vacancy.status_code == 200
    assert duplicate_vacancy.json()["id"] == saved_vacancy.json()["id"]
    assert duplicate_vacancy.json()["vacancy_title"] == "Data Analyst updated"

    outcome = profile_client.post(
        f"/v1/users/350/career-plan/actions/{saved_vacancy.json()['id']}/outcome",
        json={"status": "applied", "note": "sent resume"},
    )
    assert outcome.status_code == 200
    assert outcome.json()["application_status"] == "applied"
    assert outcome.json()["status"] == "in_progress"

    patched_plan = profile_client.patch("/v1/users/350/career-plan", json={"status": "completed"})
    assert patched_plan.status_code == 200
    assert patched_plan.json()["status"] == "completed"

    fetched_plan = profile_client.get("/v1/users/350/career-plan")
    assert fetched_plan.status_code == 200
    actions = fetched_plan.json()["actions"]
    assert [action["action_type"] for action in actions] == ["learning", "saved_vacancy"]

    deleted_plan = profile_client.delete("/v1/users/350/career-plan")
    assert deleted_plan.status_code == 204

    missing_plan = profile_client.get("/v1/users/350/career-plan")
    assert missing_plan.status_code == 404
    assert missing_plan.json()["error_code"] == "CAREER_PLAN_NOT_FOUND"


def test_generate_career_plan_actions_from_skill_gap(profile_client: TestClient) -> None:
    payload = _profile_payload()
    payload["current_skills"] = []
    profile_client.put("/v1/users/351/profile", json=payload)
    profile_client.put("/v1/users/351/career-plan", json={})

    locked = profile_client.post("/v1/users/351/career-plan/generate-actions", json={"limit": 3})
    assert locked.status_code == 402
    assert locked.json()["error_code"] == "ENTITLEMENT_REQUIRED"
    assert locked.json()["details"]["feature"] == "career_plan.generate_actions"

    profile_client.portal.call(_set_commercial_plan, profile_client.app, 351, "pro")

    generated = profile_client.post("/v1/users/351/career-plan/generate-actions", json={"limit": 3})

    assert generated.status_code == 200
    actions = generated.json()["actions"]
    assert len(actions) == 1
    assert actions[0]["skill_name"] == "python"
    assert actions[0]["recommendation_source"] == "skill_gap"
    assert actions[0]["reason"]
    assert actions[0]["due_date"]
    assert actions[0]["review_date"] == actions[0]["due_date"]
    assert actions[0]["evidence"]["skill_name"] == "python"

    repeated = profile_client.post("/v1/users/351/career-plan/generate-actions", json={"limit": 3})
    assert repeated.status_code == 200
    assert len(repeated.json()["actions"]) == 1


def test_career_plan_events_are_recorded(profile_client: TestClient) -> None:
    profile_client.put("/v1/users/352/profile", json=_profile_payload())
    profile_client.put("/v1/users/352/career-plan", json={})
    saved = profile_client.post(
        "/v1/users/352/career-plan/saved-vacancies",
        json={"hh_vacancy_id": "777", "title": "Data Analyst", "url": "https://hh.ru/vacancy/777"},
    )
    profile_client.post(
        f"/v1/users/352/career-plan/actions/{saved.json()['id']}/outcome",
        json={"status": "rejected"},
    )

    async def _events() -> list[str]:
        async with profile_client.app.state.session_maker() as session:
            rows = list((await session.scalars(select(ProductEvent).order_by(ProductEvent.id))).all())
        return [row.event_type for row in rows]

    event_types = profile_client.portal.call(_events)
    assert "vacancy_saved" in event_types
    assert "application_outcome" in event_types


def test_product_event_ingest_validates_and_redacts_payload(profile_client: TestClient) -> None:
    response = profile_client.post(
        "/v1/users/360/product-events",
        json={
            "event_name": "first_session_step_clicked",
            "surface": "web",
            "entity_type": "first_session_step",
            "entity_id": "market",
            "session_id": "session-abc",
            "correlation_id": "corr-abc",
            "metadata": {
                "step_id": "market",
                "dataset_run_id": "run-1",
                "query": "raw private search",
                "telegram_user_id": 360,
                "billingEmail": "buyer@example.com",
                "presignedUrl": "https://storage.local/resume.pdf?signature=secret",
                "rawPayload": {"provider": "raw"},
                "nested": {"token": "secret", "safe": "ok", "apiKey": "secret"},
            },
        },
        headers={"X-Request-ID": "req-product-event"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_name"] == "first_session_step_clicked"
    assert body["surface"] == "web"
    assert body["request_id"] == "req-product-event"
    assert body["session_id"] == "session-abc"
    assert body["correlation_id"] == "corr-abc"
    assert body["metadata"]["step_id"] == "market"
    assert body["metadata"]["query"] == "[redacted]"
    assert body["metadata"]["telegram_user_id"] == "[redacted]"
    assert body["metadata"]["billingEmail"] == "[redacted]"
    assert body["metadata"]["presignedUrl"] == "[redacted]"
    assert body["metadata"]["rawPayload"] == "[redacted]"
    assert body["metadata"]["nested"]["token"] == "[redacted]"
    assert body["metadata"]["nested"]["apiKey"] == "[redacted]"
    assert body["metadata"]["nested"]["safe"] == "ok"

    invalid = profile_client.post(
        "/v1/users/360/product-events",
        json={"event_name": "raw_click", "surface": "web", "metadata": {}},
    )

    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "INVALID_PRODUCT_EVENT"


def test_product_loop_summary_reports_pm_funnel_counts(
    profile_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    profile_client.put("/v1/users/353/profile", json=_profile_payload())
    profile_client.put("/v1/users/353/career-plan", json={})
    action = profile_client.post(
        "/v1/users/353/career-plan/actions",
        json={
            "title": "Ship a portfolio case",
            "action_type": "portfolio",
            "status": "planned",
            "source": "web",
        },
    ).json()
    profile_client.patch(f"/v1/users/353/career-plan/actions/{action['id']}", json={"status": "done"})
    saved = profile_client.post(
        "/v1/users/353/career-plan/saved-vacancies",
        json={
            "hh_vacancy_id": "888",
            "title": "Data Analyst",
            "url": "https://hh.ru/vacancy/888",
            "source": "bot",
        },
    ).json()
    profile_client.post(
        f"/v1/users/353/career-plan/actions/{saved['id']}/outcome",
        json={"status": "applied", "source": "bot"},
    )
    profile_client.portal.call(
        _add_product_event,
        profile_client.app,
        353,
        "digest_preview_viewed",
        "web",
        {"trust_tier": "limited_sample"},
    )
    profile_client.portal.call(_add_product_event, profile_client.app, 353, "weekly_returned", "digest")
    profile_client.portal.call(
        _add_product_event,
        profile_client.app,
        353,
        "first_session_step_clicked",
        "web",
        {"step_id": "market"},
    )
    profile_client.portal.call(
        _add_product_event,
        profile_client.app,
        353,
        "search_degraded_warning_shown",
        "web",
        {"trust_tier": "degraded_search", "search_state": "fallback"},
    )

    response = profile_client.get("/v1/admin/product-loop-summary?days=30", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["window_days"] == 30
    assert body["users_total"] == 1
    assert body["profiles_total"] == 1
    assert body["career_plans_total"] == 1
    assert body["recent_active_users"] == 1
    assert body["users_with_saved_vacancy"] == 1
    assert body["users_with_application_outcome"] == 1
    assert body["career_actions_total"] == 2
    assert body["completed_actions_total"] == 1
    assert body["saved_vacancies_total"] == 1
    assert body["application_outcomes_total"] == 2
    assert body["recent_application_outcomes_total"] == 2
    assert body["recent_product_events_by_type"]["profile_completed"] == 1
    assert body["recent_product_events_by_type"]["action_created"] == 1
    assert body["recent_product_events_by_type"]["action_completed"] == 1
    assert body["recent_product_events_by_type"]["vacancy_saved"] == 1
    assert body["recent_product_events_by_type"]["application_outcome"] == 1
    assert body["recent_product_events_by_type"]["digest_preview_viewed"] == 1
    assert body["recent_product_events_by_type"]["weekly_returned"] == 1
    assert body["recent_product_events_by_type"]["first_session_step_clicked"] == 1
    assert body["recent_product_events_by_type"]["search_degraded_warning_shown"] == 1
    assert body["recent_product_events_by_source"]["web"] == 4
    assert body["recent_product_events_by_source"]["bot"] == 2
    assert body["recent_product_events_by_source"]["digest"] == 1
    assert body["activation_conversion_by_source"]["web"] == 1.0
    assert body["weekly_return_users_by_source"]["digest"] == 1
    assert body["digest_engagement_users_by_source"]["web"] == 1
    assert body["trust_tier_distribution"] == {"limited_sample": 1, "degraded_search": 1}
    assert body["degraded_search_exposures"] == 1
    assert body["cohort_weeks"][0]["users_started"] == 1
    assert body["cohort_weeks"][0]["active_users"] == 1
    assert body["cohort_weeks"][0]["weekly_return_users"] == 1
    assert body["cohort_weeks"][0]["digest_engagement_users"] == 1
    assert body["cohort_weeks"][0]["events_by_surface"]["web"] == 4
    assert body["career_actions_by_type"] == {"portfolio": 1, "saved_vacancy": 1}
    assert body["career_actions_by_recommendation_source"] == {"manual": 2}
    assert body["recent_application_outcomes_by_status"] == {"applied": 1, "saved": 1}
    assert "telegram_user_id" not in str(body)


def test_admin_users_list(profile_client: TestClient, admin_headers: dict[str, str]) -> None:
    profile_client.put("/v1/users/401/profile", json=_profile_payload())
    profile_client.put("/v1/users/402/profile", json=_profile_payload())

    response = profile_client.get("/v1/admin/users", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["telegram_user_id"] for item in body] == [401, 402]
    assert all(item["has_profile"] for item in body)
