from __future__ import annotations

import asyncio
import importlib

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp.test_utils import TestClient, TestServer
from telegram_bot.config import Settings, SettingsError, WebhookSettings
from telegram_bot.main import _create_alert_receiver_application, _create_webhook_application

bot_main = importlib.import_module("telegram_bot.main")


def _set_common_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setenv("SKILLRA_API_BASE_URL", "http://api")
    monkeypatch.setenv("SKILLRA_API_TOKEN", "token")
    monkeypatch.setenv("SKILLRA_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "")


def test_settings_require_webhook_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com/custom")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "secret")

    settings = Settings.from_env()

    assert settings.bot.mode == "webhook"
    assert settings.webhook
    assert settings.webhook.path == "/custom"


def test_settings_missing_secret_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", raising=False)

    with pytest.raises(SettingsError):
        Settings.from_env()


def test_webhook_endpoint_requires_secret_token() -> None:
    async def _run() -> None:
        webhook_settings = WebhookSettings(
            url="https://example.com/bot",
            secret_token="secret",
            host="localhost",
            port=8081,
        )
        bot = Bot("123:TEST")
        dp = Dispatcher(storage=MemoryStorage())

        app = _create_webhook_application(bot, dp, webhook_settings)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        update_payload = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "is_bot": False, "first_name": "Test"},
                "text": "/start",
            },
        }

        try:
            response = await client.post(webhook_settings.path, json=update_payload)
            assert response.status == 401

            response = await client.post(
                webhook_settings.path,
                json=update_payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": webhook_settings.secret_token},
            )
            assert response.status == 200
        finally:
            await client.close()
            await bot.session.close()

    asyncio.run(_run())


def test_webhook_health_endpoint() -> None:
    async def _run() -> None:
        webhook_settings = WebhookSettings(
            url="https://example.com/bot",
            secret_token="secret",
            host="localhost",
            port=8081,
        )
        bot = Bot("123:TEST")
        dp = Dispatcher(storage=MemoryStorage())

        app = _create_webhook_application(bot, dp, webhook_settings)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        try:
            response = await client.get("/health")
            assert response.status == 200
            assert await response.json() == {"status": "ok"}
        finally:
            await client.close()
            await bot.session.close()

    asyncio.run(_run())


def test_alert_receiver_accepts_alertmanager_payload() -> None:
    async def _run() -> None:
        class FakeBot:
            def __init__(self) -> None:
                self.messages: list[tuple[int, str]] = []

            async def send_message(self, chat_id: int, text: str) -> None:
                self.messages.append((chat_id, text))

        bot = FakeBot()
        app = _create_alert_receiver_application(bot, admin_ids={123})
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()

        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "SkillraSmokeAlert"},
                    "annotations": {"summary": "alert receiver smoke"},
                }
            ]
        }

        try:
            health = await client.get("/health")
            assert health.status == 200
            assert await health.json() == {"status": "ok"}

            response = await client.post("/alerts", json=payload)
            assert response.status == 200
            assert await response.json() == {"status": "ok", "alerts": 1}
            assert bot.messages == [(123, "<b>Skillra alert</b>\nfiring: SkillraSmokeAlert alert receiver smoke")]
        finally:
            await client.close()

    asyncio.run(_run())


def test_run_starts_market_listener_in_polling_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "polling")

    started: list[str] = []
    cancelled: list[bool] = []

    class FakeBot:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class FakeMiddlewareTarget:
        def middleware(self, middleware: object) -> None:
            pass

    class FakeDispatcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.update = FakeMiddlewareTarget()
            self.message = FakeMiddlewareTarget()

        def include_router(self, router: object) -> None:
            pass

        async def start_polling(self, bot: object) -> None:
            await asyncio.sleep(0)

    async def fake_listener(bot: object, redis_url: str, api_settings: object) -> None:
        started.append(redis_url)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    cleaned: list[bool] = []
    alert_admin_ids: list[set[int]] = []

    class FakeAlertRunner:
        async def cleanup(self) -> None:
            cleaned.append(True)

    async def fake_start_alert_receiver(bot: object, admin_ids: set[int]) -> FakeAlertRunner:
        alert_admin_ids.append(admin_ids)
        return FakeAlertRunner()

    monkeypatch.setattr(bot_main, "Bot", FakeBot)
    monkeypatch.setattr(bot_main, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(bot_main, "_register_lifecycle_events", lambda *args: None)
    monkeypatch.setattr(bot_main, "market_update_listener", fake_listener)
    monkeypatch.setattr(bot_main, "_start_alert_receiver", fake_start_alert_receiver)

    asyncio.run(bot_main.run())

    assert started == ["redis://localhost:6379/0"]
    assert cancelled == [True]
    assert alert_admin_ids == [set()]
    assert cleaned == [True]


def test_run_starts_market_listener_in_webhook_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("BOT_MODE", "webhook")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "secret")

    started: list[str] = []
    cancelled: list[bool] = []

    class FakeBot:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class FakeMiddlewareTarget:
        def middleware(self, middleware: object) -> None:
            pass

    class FakeDispatcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.update = FakeMiddlewareTarget()
            self.message = FakeMiddlewareTarget()

        def include_router(self, router: object) -> None:
            pass

    async def fake_listener(bot: object, redis_url: str, api_settings: object) -> None:
        started.append(redis_url)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def fake_run_webhook(bot: object, dp: object, webhook: object, admin_ids: set[int]) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(bot_main, "Bot", FakeBot)
    monkeypatch.setattr(bot_main, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(bot_main, "_register_lifecycle_events", lambda *args: None)
    monkeypatch.setattr(bot_main, "market_update_listener", fake_listener)
    monkeypatch.setattr(bot_main, "_run_webhook", fake_run_webhook)

    asyncio.run(bot_main.run())

    assert started == ["redis://localhost:6379/0"]
    assert cancelled == [True]
