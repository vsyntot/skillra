import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import admin


def _build_message(user_id: int | None) -> AsyncMock:
    message = AsyncMock()
    message.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
    return message


def test_non_admin_gets_denied() -> None:
    message = _build_message(1)
    api_client = AsyncMock()

    asyncio.run(admin.handle_admin_health(message, api_client, {2}))

    message.answer.assert_awaited_once_with(admin.ACCESS_DENIED_MESSAGE)
    api_client.data_health.assert_not_awaited()


def test_admin_triggers_reload_call() -> None:
    message = _build_message(42)
    api_client = AsyncMock()
    api_client.reload_data.return_value = {
        "status": "reloaded",
        "datastore": {"ready": True},
    }

    asyncio.run(admin.handle_admin_reload_data(message, api_client, {42}))

    api_client.reload_data.assert_awaited_once()
    message.answer.assert_awaited()
    sent_text = message.answer.await_args.args[0]
    assert "reloaded" in sent_text
