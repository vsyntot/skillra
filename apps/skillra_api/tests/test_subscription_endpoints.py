from collections.abc import Generator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.db import Base  # noqa: E402
from skillra_api.db.models import DigestHistory, User, WeeklySubscription  # noqa: E402
from skillra_api.main import create_app  # noqa: E402
from sqlalchemy import select, update


async def _prepare_database(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _set_subscription_updated_at_naive(engine, telegram_user_id: int, updated_at: datetime) -> None:
    async with engine.begin() as conn:
        user_id = select(User.id).where(User.telegram_user_id == telegram_user_id).scalar_subquery()
        await conn.execute(
            update(WeeklySubscription).where(WeeklySubscription.user_id == user_id).values(updated_at=updated_at)
        )


@pytest.fixture()
def subscription_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "subscriptions.db"
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{database_path}",
    )
    app = create_app(settings)
    engine = app.state.db_engine

    with TestClient(app) as client:
        client.portal.call(_prepare_database, engine)
        client.headers.update(auth_headers)
        yield client


def _subscription_payload() -> dict[str, object]:
    return {"active": True, "weekday": 6, "time_local": "09:00", "timezone": "UTC"}


def test_create_get_delete_subscription(subscription_client: TestClient) -> None:
    create_response = subscription_client.put("/v1/users/10/subscriptions/weekly", json=_subscription_payload())
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["telegram_user_id"] == 10
    assert created["active"] is True
    assert created["last_sent_at"] is None

    fetch_response = subscription_client.get("/v1/users/10/subscriptions/weekly")
    assert fetch_response.status_code == 200
    fetched = fetch_response.json()
    assert fetched["timezone"] == "UTC"
    assert fetched["time_local"] == "09:00"

    delete_response = subscription_client.delete("/v1/users/10/subscriptions/weekly")
    assert delete_response.status_code == 204

    missing_response = subscription_client.get("/v1/users/10/subscriptions/weekly")
    assert missing_response.status_code == 404
    assert missing_response.json()["error_code"] == "SUBSCRIPTION_NOT_FOUND"


def test_due_with_fixed_now(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 1, "time_local": "12:30", "timezone": "UTC"}
    subscription_client.put("/v1/users/20/subscriptions/weekly", json=payload)

    response = subscription_client.get("/v1/subscriptions/due", params={"now_utc": "2024-07-09T12:30:00+00:00"})
    assert response.status_code == 200
    due = response.json()["subscriptions"]
    assert len(due) == 1
    assert due[0]["telegram_user_id"] == 20


def test_due_when_scheduler_runs_late(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 0, "time_local": "12:30", "timezone": "UTC"}
    subscription_client.put("/v1/users/40/subscriptions/weekly", json=payload)

    now = "2024-07-08T12:31:00+00:00"

    first_due = subscription_client.get("/v1/subscriptions/due", params={"now_utc": now})
    assert first_due.status_code == 200
    due_subscriptions = first_due.json()["subscriptions"]
    assert len(due_subscriptions) == 1
    assert due_subscriptions[0]["telegram_user_id"] == 40

    subscription_client.post("/v1/users/40/subscriptions/weekly/mark-sent", json={"now_utc": now})

    second_due = subscription_client.get("/v1/subscriptions/due", params={"now_utc": now})
    assert second_due.status_code == 200
    assert second_due.json()["subscriptions"] == []


def test_mark_sent_prevents_repeat(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 2, "time_local": "08:15", "timezone": "UTC"}
    subscription_client.put("/v1/users/30/subscriptions/weekly", json=payload)

    now = "2024-07-10T08:15:00+00:00"

    first_due = subscription_client.get("/v1/subscriptions/due", params={"now_utc": now})
    assert first_due.status_code == 200
    assert len(first_due.json()["subscriptions"]) == 1

    mark_sent = subscription_client.post("/v1/users/30/subscriptions/weekly/mark-sent", json={"now_utc": now})
    assert mark_sent.status_code == 200
    assert mark_sent.json()["last_sent_at"] is not None

    second_due = subscription_client.get("/v1/subscriptions/due", params={"now_utc": now})
    assert second_due.status_code == 200
    assert second_due.json()["subscriptions"] == []


def test_claim_and_ack_flow(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 0, "time_local": "12:30", "timezone": "UTC"}
    subscription_client.put("/v1/users/60/subscriptions/weekly", json=payload)

    now = "2024-07-08T12:31:00+00:00"

    claim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
    assert claim.status_code == 200
    claimed = claim.json()["subscriptions"]
    assert len(claimed) == 1
    lock = claimed[0]["lock"]
    assert claimed[0]["attempt"] == 1
    assert lock

    second_claim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
    assert second_claim.status_code == 200
    assert second_claim.json()["subscriptions"] == []

    ack = subscription_client.post(
        "/v1/subscriptions/weekly/ack-sent",
        json={"telegram_user_id": 60, "lock": lock, "now_utc": now, "text_preview": "Weekly digest preview"},
    )
    assert ack.status_code == 200
    assert ack.json()["last_sent_at"] is not None

    async def _history() -> tuple[str | None, int]:
        engine = subscription_client.app.state.db_engine
        async with engine.connect() as conn:
            result = await conn.execute(
                select(DigestHistory.text_preview, DigestHistory.attempt).join(User).where(User.telegram_user_id == 60)
            )
            return result.one()

    text_preview, attempt = subscription_client.portal.call(_history)
    assert text_preview == "Weekly digest preview"
    assert attempt == 1

    after_ack = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
    assert after_ack.status_code == 200
    assert after_ack.json()["subscriptions"] == []


def test_digest_history_endpoint_paginates(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 0, "time_local": "12:30", "timezone": "UTC"}
    subscription_client.put("/v1/users/61/subscriptions/weekly", json=payload)

    for day in (8, 15):
        now = f"2024-07-{day:02d}T12:31:00+00:00"
        claim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
        lock = claim.json()["subscriptions"][0]["lock"]
        ack = subscription_client.post(
            "/v1/subscriptions/weekly/ack-sent",
            json={"telegram_user_id": 61, "lock": lock, "now_utc": now},
        )
        assert ack.status_code == 200

    response = subscription_client.get("/v1/users/61/digest/history", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1


def test_ack_failed_unlocks(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 0, "time_local": "07:00", "timezone": "UTC"}
    subscription_client.put("/v1/users/70/subscriptions/weekly", json=payload)

    now = "2024-07-08T07:05:00+00:00"

    claim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
    lock = claim.json()["subscriptions"][0]["lock"]

    ack_failed = subscription_client.post(
        "/v1/subscriptions/weekly/ack-failed",
        json={"telegram_user_id": 70, "lock": lock, "now_utc": now},
    )
    assert ack_failed.status_code == 200
    assert ack_failed.json()["last_sent_at"] is None

    reclaim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now, "stale_lock_seconds": 0})
    reclaimed = reclaim.json()["subscriptions"]
    assert len(reclaimed) == 1
    assert reclaimed[0]["attempt"] == 2


def test_ack_with_wrong_lock_fails(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 0, "time_local": "10:00", "timezone": "UTC"}
    subscription_client.put("/v1/users/80/subscriptions/weekly", json=payload)

    now = "2024-07-08T10:05:00+00:00"
    claim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
    assert claim.status_code == 200

    ack = subscription_client.post(
        "/v1/subscriptions/weekly/ack-sent",
        json={"telegram_user_id": 80, "lock": "invalid", "now_utc": now},
    )
    assert ack.status_code == 409
    assert ack.json()["error_code"] == "SUBSCRIPTION_LOCK_MISMATCH"


def test_claim_handles_naive_updated_at(subscription_client: TestClient) -> None:
    payload = {"active": True, "weekday": 0, "time_local": "12:30", "timezone": "UTC"}
    subscription_client.put("/v1/users/95/subscriptions/weekly", json=payload)

    now = "2024-07-08T12:31:00+00:00"

    claim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
    assert claim.status_code == 200
    assert len(claim.json()["subscriptions"]) == 1

    naive_updated_at = datetime(2024, 7, 8, 12, 31, 0)
    engine = subscription_client.app.state.db_engine
    subscription_client.portal.call(_set_subscription_updated_at_naive, engine, 95, naive_updated_at)

    repeat_claim = subscription_client.post("/v1/subscriptions/weekly/claim", json={"now_utc": now})
    assert repeat_claim.status_code == 200
    assert repeat_claim.json()["subscriptions"] == []


def test_upsert_validates_timezone(subscription_client: TestClient) -> None:
    response = subscription_client.put(
        "/v1/users/90/subscriptions/weekly",
        json={"active": True, "weekday": 1, "time_local": "09:00", "timezone": "Mars/Phobos"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["details"]["timezone"] == "Mars/Phobos"


def test_upsert_validates_time_format(subscription_client: TestClient) -> None:
    response = subscription_client.put(
        "/v1/users/91/subscriptions/weekly",
        json={"active": True, "weekday": 2, "time_local": "9:00", "timezone": "UTC"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["details"]["time_local"] == "9:00"
