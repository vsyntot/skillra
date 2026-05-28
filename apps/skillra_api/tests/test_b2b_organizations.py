from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings
from skillra_api.db import Base
from skillra_api.db.models import CareerAction, CareerPlan, ProductEvent, User, UserProfile, WeeklySubscription
from skillra_api.main import create_app
from sqlalchemy import select


async def _prepare_database(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture()
def b2b_client(tmp_path: Path, service_token: str, auth_headers: dict[str, str]) -> Generator[TestClient, None, None]:
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'b2b.db'}",
        meilisearch_url="",
        data_watch_interval=0,
        b2b_min_cohort_n=3,
        b2b_min_cell_n=2,
    )
    app = create_app(settings)
    engine = app.state.db_engine

    with TestClient(app) as client:
        client.portal.call(_prepare_database, engine)
        client.headers.update(auth_headers)
        yield client


def _user_key(client: TestClient, telegram_user_id: int) -> str:
    response = client.post(f"/v1/users/{telegram_user_id}/api-key")
    assert response.status_code == 200
    return str(response.json()["key"])


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "X-Skillra-Token": key}


async def _seed_cohort_activity(app, telegram_user_ids: list[int]) -> None:
    async with app.state.session_maker() as session:
        users = (await session.scalars(select(User).where(User.telegram_user_id.in_(telegram_user_ids)))).all()
        by_telegram = {user.telegram_user_id: user for user in users}
        now = datetime.now(timezone.utc)
        for index, telegram_user_id in enumerate(telegram_user_ids):
            user = by_telegram[telegram_user_id]
            if index < 2:
                session.add(
                    UserProfile(
                        user_id=user.id,
                        target_role="data",
                        target_grade="junior",
                        target_city_tier="Moscow",
                        target_work_mode="remote",
                        target_domain="analytics",
                        current_skills=["sql"],
                    )
                )
                session.add(
                    ProductEvent(user_id=user.id, event_type="market_fit_viewed", source="web", occurred_at=now)
                )
                session.add(ProductEvent(user_id=user.id, event_type="skill_gap_viewed", source="web", occurred_at=now))
                plan = CareerPlan(user_id=user.id, target_role="data", status="active")
                session.add(plan)
                await session.flush()
                session.add(
                    CareerAction(
                        plan_id=plan.id,
                        title="Close python skill gap",
                        action_type="learning",
                        status="planned",
                        skill_name="python",
                        recommendation_source="skill_gap",
                    )
                )
            if index == 0:
                session.add(
                    WeeklySubscription(
                        user_id=user.id,
                        active=True,
                        weekday=0,
                        time_local="09:00",
                        timezone="Europe/Moscow",
                    )
                )
                session.add(
                    ProductEvent(
                        user_id=user.id,
                        event_type="vacancy_search_performed",
                        source="web",
                        occurred_at=now,
                    )
                )
        await session.commit()


async def _product_events(app, event_type: str) -> list[ProductEvent]:
    async with app.state.session_maker() as session:
        events = (
            await session.scalars(
                select(ProductEvent).where(ProductEvent.event_type == event_type).order_by(ProductEvent.id.asc())
            )
        ).all()
        return list(events)


def test_user_can_create_org_and_service_token_does_not_bypass_b2b_scope(b2b_client: TestClient) -> None:
    owner_key = _user_key(b2b_client, 8101)

    response = b2b_client.post(
        "/v1/organizations",
        headers=_bearer(owner_key),
        json={"name": "HSE Career Center", "slug": "hse-career", "organization_type": "university"},
    )
    service_scope = b2b_client.get("/v1/organizations")

    assert response.status_code == 200
    assert response.json()["role"] == "owner"
    assert response.json()["slug"] == "hse-career"
    assert service_scope.status_code == 403
    assert service_scope.json()["error_code"] == "USER_API_KEY_REQUIRED"

    listed = b2b_client.get("/v1/organizations", headers=_bearer(owner_key))
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "HSE Career Center"


def test_invite_accept_attaches_member_to_org_and_cohort_with_role_guard(b2b_client: TestClient) -> None:
    owner_key = _user_key(b2b_client, 8201)
    member_key = _user_key(b2b_client, 8202)
    org = b2b_client.post("/v1/organizations", headers=_bearer(owner_key), json={"name": "Bootcamp"}).json()
    cohort = b2b_client.post(
        f"/v1/organizations/{org['id']}/cohorts",
        headers=_bearer(owner_key),
        json={"name": "Data Spring"},
    ).json()
    invite = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"cohort_id": cohort["id"], "max_uses": 1},
    ).json()

    accepted = b2b_client.post(f"/v1/invites/{invite['token']}/accept", headers=_bearer(member_key))
    members_denied = b2b_client.get(f"/v1/organizations/{org['id']}/members", headers=_bearer(member_key))
    members = b2b_client.get(f"/v1/organizations/{org['id']}/members", headers=_bearer(owner_key))
    cohort_members = b2b_client.get(
        f"/v1/organizations/{org['id']}/cohorts/{cohort['id']}/members",
        headers=_bearer(owner_key),
    )

    assert accepted.status_code == 200
    assert accepted.json()["organization"]["role"] == "member"
    assert accepted.json()["cohort"]["id"] == cohort["id"]
    assert members_denied.status_code == 403
    assert members_denied.json()["error_code"] == "ORG_ADMIN_REQUIRED"
    assert members.status_code == 200
    assert {item["role"] for item in members.json()} == {"owner", "member"}
    assert cohort_members.status_code == 200
    assert cohort_members.json()[0]["user_id"] > 0


def test_revoked_and_expired_invites_are_rejected(b2b_client: TestClient) -> None:
    owner_key = _user_key(b2b_client, 8301)
    member_key = _user_key(b2b_client, 8302)
    org = b2b_client.post("/v1/organizations", headers=_bearer(owner_key), json={"name": "Company"}).json()

    invite = b2b_client.post(f"/v1/organizations/{org['id']}/invites", headers=_bearer(owner_key), json={}).json()
    revoke = b2b_client.delete(
        f"/v1/organizations/{org['id']}/invites/{invite['id']}",
        headers=_bearer(owner_key),
    )
    revoked_accept = b2b_client.post(f"/v1/invites/{invite['token']}/accept", headers=_bearer(member_key))

    expired = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
    ).json()
    expired_accept = b2b_client.post(f"/v1/invites/{expired['token']}/accept", headers=_bearer(member_key))

    assert revoke.status_code == 200
    assert revoked_accept.status_code == 410
    assert revoked_accept.json()["error_code"] == "INVITE_REVOKED"
    assert expired_accept.status_code == 410
    assert expired_accept.json()["error_code"] == "INVITE_EXPIRED"


def test_cohort_analytics_suppression_metrics_and_csv_are_privacy_safe(b2b_client: TestClient) -> None:
    owner_key = _user_key(b2b_client, 8401)
    org = b2b_client.post("/v1/organizations", headers=_bearer(owner_key), json={"name": "Career Center"}).json()
    cohort = b2b_client.post(
        f"/v1/organizations/{org['id']}/cohorts",
        headers=_bearer(owner_key),
        json={"name": "Small Group"},
    ).json()
    small_invite = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"cohort_id": cohort["id"], "max_uses": 1},
    ).json()
    first_member_key = _user_key(b2b_client, 8402)
    b2b_client.post(f"/v1/invites/{small_invite['token']}/accept", headers=_bearer(first_member_key))

    suppressed = b2b_client.get(
        f"/v1/organizations/{org['id']}/cohorts/{cohort['id']}/analytics",
        headers=_bearer(owner_key),
    )
    assert suppressed.status_code == 200
    assert suppressed.json()["suppressed"] is True
    assert suppressed.json()["member_count_bucket"] == "<3"
    assert suppressed.json()["metrics"] == []

    invite = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"cohort_id": cohort["id"], "max_uses": 2},
    ).json()
    for telegram_user_id in [8403, 8404]:
        key = _user_key(b2b_client, telegram_user_id)
        accepted = b2b_client.post(f"/v1/invites/{invite['token']}/accept", headers=_bearer(key))
        assert accepted.status_code == 200
    b2b_client.portal.call(_seed_cohort_activity, b2b_client.app, [8402, 8403, 8404])

    analytics = b2b_client.get(
        f"/v1/organizations/{org['id']}/cohorts/{cohort['id']}/analytics",
        headers=_bearer(owner_key),
    )
    export = b2b_client.get(
        f"/v1/organizations/{org['id']}/cohorts/{cohort['id']}/export.csv",
        headers=_bearer(owner_key),
    )

    assert analytics.status_code == 200
    body = analytics.json()
    assert body["suppressed"] is False
    profile_metric = next(item for item in body["metrics"] if item["metric"] == "profile_completion_rate")
    assert profile_metric["count"] == 2
    assert profile_metric["denominator"] == 3
    assert body["skill_heatmap"][0]["skill_name"] == "python"
    assert body["skill_heatmap"][0]["users_missing_count"] == 2
    assert export.status_code == 200
    assert "profile_completion_rate" in export.text
    assert "python" in export.text
    forbidden = ["telegram_user_id", "username", "raw_resume", "note", "vacancy_title"]
    assert all(marker not in export.text for marker in forbidden)


def test_owner_transfer_requires_owner_and_records_audit_event(b2b_client: TestClient) -> None:
    owner_key = _user_key(b2b_client, 8501)
    admin_key = _user_key(b2b_client, 8502)
    member_key = _user_key(b2b_client, 8503)
    org = b2b_client.post("/v1/organizations", headers=_bearer(owner_key), json={"name": "Pilot Org"}).json()
    admin_invite = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"role": "admin"},
    ).json()
    member_invite = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"role": "member"},
    ).json()
    assert b2b_client.post(f"/v1/invites/{admin_invite['token']}/accept", headers=_bearer(admin_key)).status_code == 200
    assert (
        b2b_client.post(f"/v1/invites/{member_invite['token']}/accept", headers=_bearer(member_key)).status_code == 200
    )
    members_before = b2b_client.get(f"/v1/organizations/{org['id']}/members", headers=_bearer(owner_key)).json()
    member_user_id = next(item["user_id"] for item in members_before if item["role"] == "member")

    denied = b2b_client.patch(
        f"/v1/organizations/{org['id']}/members/{member_user_id}",
        headers=_bearer(admin_key),
        json={"role": "owner"},
    )
    transfer = b2b_client.patch(
        f"/v1/organizations/{org['id']}/members/{member_user_id}",
        headers=_bearer(owner_key),
        json={"role": "owner"},
    )
    members_after = b2b_client.get(f"/v1/organizations/{org['id']}/members", headers=_bearer(member_key))
    events = b2b_client.portal.call(_product_events, b2b_client.app, "organization_owner_transferred")

    assert denied.status_code == 403
    assert denied.json()["error_code"] == "ORG_OWNER_TRANSFER_OWNER_REQUIRED"
    assert transfer.status_code == 200
    assert transfer.json()["role"] == "owner"
    assert members_after.status_code == 200
    roles = {item["user_id"]: item["role"] for item in members_after.json()}
    assert roles[member_user_id] == "owner"
    assert list(roles.values()).count("owner") == 1
    assert events[-1].source == "admin"
    assert events[-1].entity_type == "organization"
    assert events[-1].entity_id == str(org["id"])


def test_revoke_org_member_revokes_cohort_memberships_and_records_audit(b2b_client: TestClient) -> None:
    owner_key = _user_key(b2b_client, 8601)
    member_key = _user_key(b2b_client, 8602)
    org = b2b_client.post("/v1/organizations", headers=_bearer(owner_key), json={"name": "Member Ops"}).json()
    cohort = b2b_client.post(
        f"/v1/organizations/{org['id']}/cohorts",
        headers=_bearer(owner_key),
        json={"name": "Spring"},
    ).json()
    invite = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"cohort_id": cohort["id"]},
    ).json()
    assert b2b_client.post(f"/v1/invites/{invite['token']}/accept", headers=_bearer(member_key)).status_code == 200
    members = b2b_client.get(f"/v1/organizations/{org['id']}/members", headers=_bearer(owner_key)).json()
    member_user_id = next(item["user_id"] for item in members if item["role"] == "member")

    revoke = b2b_client.patch(
        f"/v1/organizations/{org['id']}/members/{member_user_id}",
        headers=_bearer(owner_key),
        json={"status": "revoked"},
    )
    cohort_members = b2b_client.get(
        f"/v1/organizations/{org['id']}/cohorts/{cohort['id']}/members",
        headers=_bearer(owner_key),
    )
    events = b2b_client.portal.call(_product_events, b2b_client.app, "organization_member_updated")

    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"
    assert cohort_members.status_code == 200
    assert cohort_members.json()[0]["status"] == "revoked"
    assert events[-1].payload["to_status"] == "revoked"
    assert events[-1].payload["revoked_cohort_memberships"] == 1


def test_cohort_member_can_be_moved_between_cohorts(b2b_client: TestClient) -> None:
    owner_key = _user_key(b2b_client, 8701)
    member_key = _user_key(b2b_client, 8702)
    org = b2b_client.post("/v1/organizations", headers=_bearer(owner_key), json={"name": "Cohort Ops"}).json()
    first = b2b_client.post(
        f"/v1/organizations/{org['id']}/cohorts",
        headers=_bearer(owner_key),
        json={"name": "First"},
    ).json()
    second = b2b_client.post(
        f"/v1/organizations/{org['id']}/cohorts",
        headers=_bearer(owner_key),
        json={"name": "Second"},
    ).json()
    invite = b2b_client.post(
        f"/v1/organizations/{org['id']}/invites",
        headers=_bearer(owner_key),
        json={"cohort_id": first["id"]},
    ).json()
    assert b2b_client.post(f"/v1/invites/{invite['token']}/accept", headers=_bearer(member_key)).status_code == 200
    member_user_id = next(
        item["user_id"]
        for item in b2b_client.get(f"/v1/organizations/{org['id']}/members", headers=_bearer(owner_key)).json()
        if item["role"] == "member"
    )

    move = b2b_client.patch(
        f"/v1/organizations/{org['id']}/cohorts/{first['id']}/members/{member_user_id}",
        headers=_bearer(owner_key),
        json={"target_cohort_id": second["id"]},
    )
    first_members = b2b_client.get(
        f"/v1/organizations/{org['id']}/cohorts/{first['id']}/members",
        headers=_bearer(owner_key),
    ).json()
    second_members = b2b_client.get(
        f"/v1/organizations/{org['id']}/cohorts/{second['id']}/members",
        headers=_bearer(owner_key),
    ).json()
    events = b2b_client.portal.call(_product_events, b2b_client.app, "cohort_member_updated")

    assert move.status_code == 200
    assert move.json()["status"] == "active"
    assert first_members[0]["status"] == "revoked"
    assert second_members[0]["status"] == "active"
    assert events[-1].payload["moved"] is True
    assert events[-1].payload["to_cohort_id"] == second["id"]
