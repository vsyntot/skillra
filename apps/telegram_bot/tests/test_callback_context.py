from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from telegram_bot.services.callback_context import CallbackContextError, CallbackContextStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []
        self.closed = False

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
        self.values[name] = value
        return True

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def delete(self, name: str) -> int:
        self.deleted.append(name)
        return 1 if self.values.pop(name, None) is not None else 0

    async def aclose(self) -> None:
        self.closed = True


def _token(callback_data: str) -> str:
    return callback_data.rsplit(":", maxsplit=1)[-1]


def test_callback_context_resolves_after_new_store_instance() -> None:
    async def _run() -> None:
        redis = FakeRedis()
        now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
        store = CallbackContextStore(signing_secret="secret", redis_client=redis, now=lambda: now)
        callback_data = await store.create_callback_data(
            namespace="srch",
            action="save",
            user_id=42,
            entity_type="vacancy",
            entity_id="101",
            payload={"hh_vacancy_id": "101", "title": "Data Analyst"},
            ttl_seconds=900,
        )

        restarted_store = CallbackContextStore(signing_secret="secret", redis_client=redis, now=lambda: now)
        context = await restarted_store.resolve(
            namespace="srch",
            action="save",
            token=_token(callback_data),
            user_id=42,
        )

        assert context.user_id == 42
        assert context.entity_id == "101"
        assert context.payload["title"] == "Data Analyst"

    asyncio.run(_run())


def test_callback_context_rejects_wrong_user() -> None:
    async def _run() -> None:
        redis = FakeRedis()
        now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
        store = CallbackContextStore(signing_secret="secret", redis_client=redis, now=lambda: now)
        callback_data = await store.create_callback_data(
            namespace="srch",
            action="save",
            user_id=42,
            entity_type="vacancy",
            entity_id="101",
            payload={"hh_vacancy_id": "101"},
            ttl_seconds=900,
        )

        with pytest.raises(CallbackContextError) as excinfo:
            await store.resolve(namespace="srch", action="save", token=_token(callback_data), user_id=99)

        assert excinfo.value.reason == "wrong_user"

    asyncio.run(_run())


def test_callback_context_rejects_expired_and_deletes_key() -> None:
    async def _run() -> None:
        redis = FakeRedis()
        current_time = [datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)]
        store = CallbackContextStore(signing_secret="secret", redis_client=redis, now=lambda: current_time[0])
        callback_data = await store.create_callback_data(
            namespace="srch",
            action="save",
            user_id=42,
            entity_type="vacancy",
            entity_id="101",
            payload={"hh_vacancy_id": "101"},
            ttl_seconds=60,
        )
        token = _token(callback_data)
        key = f"bot:callback:srch:{token}"
        current_time[0] = current_time[0] + timedelta(seconds=61)

        with pytest.raises(CallbackContextError) as excinfo:
            await store.resolve(namespace="srch", action="save", token=token, user_id=42)

        assert excinfo.value.reason == "expired"
        assert key in redis.deleted
        assert key not in redis.values

    asyncio.run(_run())


def test_callback_context_rejects_tampered_signature_fields() -> None:
    async def _run() -> None:
        redis = FakeRedis()
        now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
        store = CallbackContextStore(signing_secret="secret", redis_client=redis, now=lambda: now)
        callback_data = await store.create_callback_data(
            namespace="srch",
            action="save",
            user_id=42,
            entity_type="vacancy",
            entity_id="101",
            payload={"hh_vacancy_id": "101"},
            ttl_seconds=900,
        )
        token = _token(callback_data)
        key = f"bot:callback:srch:{token}"
        value = json.loads(redis.values[key])
        value["entity_id"] = "999"
        redis.values[key] = json.dumps(value)

        with pytest.raises(CallbackContextError) as excinfo:
            await store.resolve(namespace="srch", action="save", token=token, user_id=42)

        assert excinfo.value.reason == "invalid"

    asyncio.run(_run())


def test_callback_context_reports_missing_key() -> None:
    async def _run() -> None:
        redis = FakeRedis()
        now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
        store = CallbackContextStore(signing_secret="secret", redis_client=redis, now=lambda: now)

        with pytest.raises(CallbackContextError) as excinfo:
            await store.resolve(namespace="srch", action="save", token="missing", user_id=42)

        assert excinfo.value.reason == "missing"

    asyncio.run(_run())
