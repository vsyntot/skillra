from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import api_key
from telegram_bot.services.errors import SkillraApiError


def test_format_new_api_key_warns_about_one_time_display() -> None:
    text = api_key.format_new_api_key(
        {
            "key": "sk_42_secret",
            "key_prefix": "sk_42_se",
            "created_at": "2026-05-19T10:00:00Z",
        }
    )

    assert "повторно показать его нельзя" in text
    assert "<code>sk_42_secret</code>" in text
    assert "sk_42_se" in text


def test_show_api_key_creates_when_missing() -> None:
    async def _run() -> None:
        api_client = AsyncMock()
        api_client.get_user_api_key_status.side_effect = SkillraApiError(
            error_code=None,
            error_message="not found",
            status_code=404,
            request_id="req",
            payload=None,
        )
        api_client.create_user_api_key.return_value = {
            "key": "sk_42_secret",
            "key_prefix": "sk_42_se",
            "created_at": "2026-05-19T10:00:00Z",
        }
        message = AsyncMock()
        message.from_user = SimpleNamespace(id=42)

        await api_key.show_or_create_api_key(message, api_client)

        api_client.create_user_api_key.assert_awaited_once_with(42)
        answer_text = message.answer.await_args.args[0]
        assert "sk_42_secret" in answer_text

    asyncio.run(_run())
