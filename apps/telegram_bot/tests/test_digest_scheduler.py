import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from aiogram import exceptions as tg_exceptions
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile
from digest_worker.worker import DigestWorker, heartbeat_is_fresh, write_heartbeat, write_worker_metrics
from telegram_bot.services.errors import SkillraApiError


def _claimed(lock: str, telegram_user_id: int = 42) -> list[dict[str, object]]:
    return [
        {
            "telegram_user_id": telegram_user_id,
            "lock": lock,
            "timezone": "Europe/Moscow",
        }
    ]


def test_process_tick_sends_due_subscriptions() -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-42")
    api_client.get_digest_preview.return_value = {
        "format": "HTML",
        "text": "<b>Digest</b>",
    }
    api_client.get_digest_chart.return_value = b"digest-chart"

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01)

    asyncio.run(scheduler.process_tick())

    api_client.claim_weekly_digest_subscriptions.assert_awaited_once()
    api_client.get_digest_preview.assert_awaited_once_with(42)
    bot.send_message.assert_awaited_once_with(42, "<b>Digest</b>", parse_mode=ParseMode.HTML)
    api_client.ack_weekly_digest_subscription.assert_awaited_once_with(
        42, "lock-42", sent=True, text_preview="<b>Digest</b>"
    )
    api_client.get_digest_chart.assert_awaited_once_with(42)
    bot.send_photo.assert_awaited_once()
    args, _ = bot.send_photo.await_args
    assert args[0] == 42
    assert isinstance(args[1], BufferedInputFile)


def test_process_tick_writes_heartbeat(tmp_path: Path) -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = []
    heartbeat_path = tmp_path / "digest_worker_heartbeat"

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01, heartbeat_path=str(heartbeat_path))

    asyncio.run(scheduler.process_tick())

    assert heartbeat_path.exists()
    assert heartbeat_is_fresh(str(heartbeat_path), 300)


def test_process_tick_writes_worker_metrics(tmp_path: Path) -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-42")
    api_client.get_digest_preview.return_value = {
        "format": "HTML",
        "text": "<b>Digest</b>",
    }
    api_client.get_digest_chart.return_value = b""
    metrics_path = tmp_path / "skillra_digest_worker_events.prom"

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01, metrics_path=str(metrics_path))

    asyncio.run(scheduler.process_tick())

    text = metrics_path.read_text(encoding="utf-8")
    assert "skillra_digest_worker_claimed_total 1" in text
    assert "skillra_digest_worker_sent_total 1" in text
    assert "skillra_digest_worker_failed_total 0" in text
    assert "skillra_digest_worker_ack_failed_total 0" in text
    assert "skillra_digest_worker_last_tick_timestamp_seconds " in text
    assert not metrics_path.with_suffix(".prom.tmp").exists()


def test_worker_metrics_record_ack_failures(tmp_path: Path) -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-202", telegram_user_id=202)
    api_client.get_digest_preview.return_value = {
        "format": "HTML",
        "text": "<b>Digest</b>",
    }
    api_client.get_digest_chart.return_value = b""
    api_client.ack_weekly_digest_subscription.side_effect = SkillraApiError(
        error_code=None,
        error_message="Failed to ack",
        status_code=503,
        request_id="req-ack",
        payload=None,
    )
    metrics_path = tmp_path / "skillra_digest_worker_events.prom"

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01, metrics_path=str(metrics_path))

    asyncio.run(scheduler.process_tick())

    text = metrics_path.read_text(encoding="utf-8")
    assert "skillra_digest_worker_claimed_total 1" in text
    assert "skillra_digest_worker_sent_total 1" in text
    assert "skillra_digest_worker_ack_failed_total 1" in text


def test_heartbeat_freshness_helper(tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "digest_worker_heartbeat"
    write_heartbeat(str(heartbeat_path), timestamp=1000.0)

    assert heartbeat_is_fresh(str(heartbeat_path), 300.0, now=1200.0)
    assert not heartbeat_is_fresh(str(heartbeat_path), 300.0, now=1401.0)
    assert not heartbeat_is_fresh(str(tmp_path / "missing"), 300.0, now=1200.0)


def test_write_worker_metrics_uses_textfile_format(tmp_path: Path) -> None:
    metrics_path = tmp_path / "skillra_digest_worker_events.prom"

    write_worker_metrics(
        str(metrics_path),
        {
            "claimed_total": 3,
            "sent_total": 2,
            "failed_total": 1,
            "ack_failed_total": 1,
            "last_tick_timestamp_seconds": 1234,
        },
    )

    text = metrics_path.read_text(encoding="utf-8")
    assert "# TYPE skillra_digest_worker_claimed_total counter" in text
    assert "skillra_digest_worker_claimed_total 3" in text
    assert "skillra_digest_worker_sent_total 2" in text
    assert "skillra_digest_worker_failed_total 1" in text
    assert "skillra_digest_worker_ack_failed_total 1" in text
    assert "skillra_digest_worker_last_tick_timestamp_seconds 1234" in text


def test_process_tick_deactivates_unavailable_user() -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-99", telegram_user_id=99)
    api_client.get_digest_preview.return_value = {
        "format": "HTML",
        "text": "<b>Digest</b>",
    }
    api_client.get_digest_chart.return_value = b""
    bot.send_message.side_effect = tg_exceptions.TelegramForbiddenError(method="sendMessage", message="Forbidden")

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01)

    asyncio.run(scheduler.process_tick())

    api_client.delete_weekly_subscription.assert_awaited_once_with(99)
    api_client.ack_weekly_digest_subscription.assert_awaited_once_with(99, "lock-99", sent=False)


def test_process_subscription_backward_compat_content_only() -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-7", telegram_user_id=7)
    api_client.get_digest_preview.return_value = {
        "format": "HTML",
        "content": "<b>Compat digest</b>",
    }
    api_client.get_digest_chart.return_value = b""

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01)

    asyncio.run(scheduler.process_tick())

    bot.send_message.assert_awaited_once_with(7, "<b>Compat digest</b>", parse_mode=ParseMode.HTML)
    api_client.ack_weekly_digest_subscription.assert_awaited_once_with(
        7, "lock-7", sent=True, text_preview="<b>Compat digest</b>"
    )


def test_process_tick_marks_sent_when_chart_fails() -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-101", telegram_user_id=101)
    api_client.get_digest_preview.return_value = {
        "format": "HTML",
        "text": "<b>Digest</b>",
    }
    api_client.get_digest_chart.side_effect = SkillraApiError(
        error_code=None,
        error_message="Server error",
        status_code=500,
        request_id="req-chart",
        payload=None,
    )

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01)

    asyncio.run(scheduler.process_tick())

    bot.send_message.assert_awaited_once()
    api_client.ack_weekly_digest_subscription.assert_awaited_once_with(
        101, "lock-101", sent=True, text_preview="<b>Digest</b>"
    )
    api_client.get_digest_chart.assert_awaited_once_with(101)
    bot.send_photo.assert_not_awaited()


def test_ack_error_does_not_break_scheduler() -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-202", telegram_user_id=202)
    api_client.get_digest_preview.return_value = {
        "format": "MarkdownV2",
        "text": "*Digest*",
    }
    api_client.get_digest_chart.return_value = b""
    api_client.ack_weekly_digest_subscription.side_effect = SkillraApiError(
        error_code=None,
        error_message="Failed to ack",
        status_code=503,
        request_id="req-ack",
        payload=None,
    )

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01)

    asyncio.run(scheduler.process_tick())

    api_client.claim_weekly_digest_subscriptions.assert_awaited_once()
    bot.send_message.assert_awaited_once_with(202, "*Digest*", parse_mode=ParseMode.MARKDOWN_V2)
    api_client.ack_weekly_digest_subscription.assert_awaited_once_with(
        202, "lock-202", sent=True, text_preview="*Digest*"
    )
    api_client.get_digest_chart.assert_awaited_once_with(202)


def test_chart_send_failure_keeps_mark_sent_after_text() -> None:
    bot = AsyncMock()
    api_client = AsyncMock()
    api_client.claim_weekly_digest_subscriptions.return_value = _claimed("lock-303", telegram_user_id=303)
    api_client.get_digest_preview.return_value = {
        "format": "HTML",
        "text": "<b>Digest</b>",
    }
    api_client.get_digest_chart.return_value = b"chart-bytes"
    bot.send_photo.side_effect = Exception("send-photo failed")

    scheduler = DigestWorker(bot, api_client, poll_interval=0.01)

    asyncio.run(scheduler.process_tick())

    bot.send_message.assert_awaited_once_with(303, "<b>Digest</b>", parse_mode=ParseMode.HTML)
    api_client.ack_weekly_digest_subscription.assert_awaited_once_with(
        303, "lock-303", sent=True, text_preview="<b>Digest</b>"
    )
    bot.send_photo.assert_awaited_once()
