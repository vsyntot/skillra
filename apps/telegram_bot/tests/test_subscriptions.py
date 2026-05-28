import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers import subscriptions


def test_format_subscription_summary_contains_schedule() -> None:
    text = subscriptions.format_subscription_summary(
        {
            "weekday": 0,
            "time_local": "10:00",
            "timezone": "Europe/Moscow",
        }
    )

    assert "Подписка" in text
    assert "Понедельник" in text
    assert "10:00" in text
    assert "Europe/Moscow" in text


def test_collect_time_options_preserves_default() -> None:
    options = subscriptions._collect_time_options("08:00")

    assert options[0] == "08:00"
    assert "09:00" in options


def test_collect_timezone_options_preserves_default() -> None:
    options = subscriptions._collect_timezone_options("Asia/Tomsk")

    assert options[0] == "Asia/Tomsk"
    assert "Europe/Moscow" in options


def test_save_subscription_uses_timezone_from_state() -> None:
    api_client = AsyncMock()
    api_client.upsert_weekly_subscription.return_value = {
        "weekday": 2,
        "time_local": "09:00",
        "timezone": "Asia/Novosibirsk",
    }

    state = AsyncMock()
    state.get_data.return_value = {
        "weekday": 2,
        "time_local": "09:00",
        "timezone": "Asia/Novosibirsk",
    }

    message = AsyncMock()

    asyncio.run(subscriptions._save_subscription(message, 123, state, api_client, None))

    api_client.upsert_weekly_subscription.assert_awaited_once_with(
        123,
        {
            "active": True,
            "weekday": 2,
            "time_local": "09:00",
            "timezone": "Asia/Novosibirsk",
        },
    )


def test_is_valid_time() -> None:
    assert subscriptions._is_valid_time("09:30") is True
    assert subscriptions._is_valid_time("9:30") is False
    assert subscriptions._is_valid_time("24:00") is False


def test_is_valid_timezone() -> None:
    assert subscriptions._is_valid_timezone("Europe/Moscow") is True
    assert subscriptions._is_valid_timezone("Mars/Phobos") is False


def test_compute_next_send_datetime_same_day_future() -> None:
    next_send = subscriptions.compute_next_send_datetime(
        weekday=0,
        time_local="12:00",
        timezone_name="UTC",
        last_sent_at=None,
        now=datetime(2024, 7, 8, 10, 0, tzinfo=timezone.utc),
    )

    assert next_send == datetime(2024, 7, 8, 12, 0, tzinfo=timezone.utc)


def test_compute_next_send_datetime_rolls_to_next_week_after_send() -> None:
    next_send = subscriptions.compute_next_send_datetime(
        weekday=0,
        time_local="12:00",
        timezone_name="UTC",
        last_sent_at=datetime(2024, 7, 8, 12, 0, tzinfo=timezone.utc),
        now=datetime(2024, 7, 8, 10, 0, tzinfo=timezone.utc),
    )

    assert next_send == datetime(2024, 7, 15, 12, 0, tzinfo=timezone.utc)


def test_pause_and_resume_subscription_toggle_active() -> None:
    async def _run() -> None:
        api_client = AsyncMock()
        api_client.get_weekly_subscription.return_value = {
            "active": True,
            "weekday": 1,
            "time_local": "09:00",
            "timezone": "UTC",
        }
        message = AsyncMock()
        message.from_user = SimpleNamespace(id=123)

        await subscriptions.pause_subscription(message, api_client)
        api_client.upsert_weekly_subscription.assert_awaited_with(
            123,
            {"active": False, "weekday": 1, "time_local": "09:00", "timezone": "UTC"},
        )

        await subscriptions.resume_subscription(message, api_client)
        api_client.upsert_weekly_subscription.assert_awaited_with(
            123,
            {"active": True, "weekday": 1, "time_local": "09:00", "timezone": "UTC"},
        )

    asyncio.run(_run())
