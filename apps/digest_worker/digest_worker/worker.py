"""Standalone digest worker that claims due subscriptions and sends Telegram digests."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from aiogram import Bot
from aiogram import exceptions as tg_exceptions
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile
from telegram_bot.config import SettingsError, SkillraApiSettings
from telegram_bot.logging_config import setup_logging
from telegram_bot.logging_utils import mask_user_id
from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.errors import SkillraApiError

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_PATH = "/tmp/digest_worker_heartbeat"
DEFAULT_METRIC_VALUES = {
    "claimed_total": 0,
    "sent_total": 0,
    "failed_total": 0,
    "ack_failed_total": 0,
    "last_tick_timestamp_seconds": 0,
}


class DigestWorker:
    """Background worker that sends weekly digest previews to due subscribers."""

    def __init__(
        self,
        bot: Bot,
        api_client: SkillraApiClient,
        poll_interval: float,
        send_semaphore_limit: int = 5,
        min_send_interval: float = 0.05,
        heartbeat_path: str | None = DEFAULT_HEARTBEAT_PATH,
        metrics_path: str | None = None,
    ) -> None:
        self._bot = bot
        self._api_client = api_client
        self._poll_interval = poll_interval
        self._heartbeat_path = heartbeat_path
        self._metrics_path = metrics_path or os.getenv("DIGEST_WORKER_METRICS_PATH")
        self._metric_values = dict(DEFAULT_METRIC_VALUES)
        self._stop_event = asyncio.Event()
        self._send_semaphore = asyncio.Semaphore(send_semaphore_limit)
        self._send_interval_lock = asyncio.Lock()
        self._min_send_interval = min_send_interval
        self._last_send_timestamp = 0.0

    def stop(self) -> None:
        """Signal the worker to stop gracefully."""

        self._stop_event.set()

    async def run(self) -> None:
        """Run polling loop until stopped."""

        logger.info("Starting digest worker", extra={"interval": self._poll_interval})

        try:
            while not self._stop_event.is_set():
                try:
                    await self.process_tick()
                except Exception:  # noqa: BLE001
                    logger.exception("Digest worker tick failed")
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            logger.info("Digest worker cancelled")
            raise

    async def process_tick(self) -> None:
        """Claim due subscriptions and process them one by one."""

        self._write_heartbeat()
        self._record_tick()
        try:
            due_subscriptions = await self._api_client.claim_weekly_digest_subscriptions()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to claim due subscriptions")
            self._increment_metric("failed_total")
            return

        self._increment_metric("claimed_total", len(due_subscriptions))
        for subscription in due_subscriptions:
            telegram_user_id = subscription.get("telegram_user_id")
            lock = subscription.get("lock")
            if telegram_user_id is None or not lock:
                self._increment_metric("failed_total")
                continue

            try:
                await self._process_subscription(int(telegram_user_id), str(lock))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Unexpected error while processing subscription",
                    extra={"user_id": mask_user_id(telegram_user_id)},
                )
                self._increment_metric("failed_total")

    async def _process_subscription(self, telegram_user_id: int, lock: str) -> None:
        masked_user_id = mask_user_id(telegram_user_id)
        try:
            preview = await self._api_client.get_digest_preview(telegram_user_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to fetch digest preview", extra={"user_id": masked_user_id})
            self._increment_metric("failed_total")
            await self._ack_subscription(telegram_user_id, lock, sent=False)
            return

        content = preview.get("text") or preview.get("content")
        if not content:
            logger.warning("Empty digest preview", extra={"user_id": masked_user_id})
            self._increment_metric("failed_total")
            await self._ack_subscription(telegram_user_id, lock, sent=False)
            return

        try:
            parse_mode = self._parse_mode_from_format(preview.get("format"))
            await self._send_with_rate_limit(telegram_user_id, content, parse_mode)
            self._increment_metric("sent_total")
        except (tg_exceptions.TelegramForbiddenError, tg_exceptions.TelegramNotFound):
            logger.warning("Telegram user unavailable, deactivating subscription", extra={"user_id": masked_user_id})
            self._increment_metric("failed_total")
            await self._delete_subscription(telegram_user_id)
            await self._ack_subscription(telegram_user_id, lock, sent=False)
            return
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send digest", extra={"user_id": masked_user_id})
            self._increment_metric("failed_total")
            await self._ack_subscription(telegram_user_id, lock, sent=False)
            return

        await self._try_send_chart(telegram_user_id)
        await self._ack_subscription(telegram_user_id, lock, sent=True, text_preview=content[:500])

    async def _send_with_rate_limit(self, telegram_user_id: int, content: str, parse_mode: ParseMode | None) -> None:
        async with self._send_semaphore:
            await self._enforce_send_interval()
            await self._bot.send_message(telegram_user_id, content, parse_mode=parse_mode)

    async def _send_photo_with_rate_limit(self, telegram_user_id: int, photo_bytes: bytes) -> None:
        async with self._send_semaphore:
            await self._enforce_send_interval()
            await self._bot.send_photo(
                telegram_user_id,
                BufferedInputFile(photo_bytes, filename="digest.png"),
            )

    async def _enforce_send_interval(self) -> None:
        async with self._send_interval_lock:
            now = asyncio.get_running_loop().time()
            sleep_for = self._min_send_interval - (now - self._last_send_timestamp)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            self._last_send_timestamp = asyncio.get_running_loop().time()

    @staticmethod
    def _parse_mode_from_format(format_hint: str | None) -> ParseMode | None:
        if not format_hint:
            return None

        try:
            return ParseMode(format_hint)
        except ValueError:
            return None

    async def _try_send_chart(self, telegram_user_id: int) -> None:
        masked_user_id = mask_user_id(telegram_user_id)
        try:
            chart_bytes = await self._api_client.get_digest_chart(telegram_user_id)
        except SkillraApiError as exc:
            logger.warning(
                "Digest chart unavailable",
                extra={"user_id": masked_user_id, "status": exc.status_code},
            )
            return
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error while fetching digest chart", extra={"user_id": masked_user_id})
            return

        if not chart_bytes:
            logger.warning("Empty digest chart", extra={"user_id": masked_user_id})
            return

        try:
            await self._send_photo_with_rate_limit(telegram_user_id, chart_bytes)
        except (tg_exceptions.TelegramForbiddenError, tg_exceptions.TelegramNotFound):
            logger.warning("Telegram user unavailable for chart", extra={"user_id": masked_user_id})
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send digest chart", extra={"user_id": masked_user_id})

    async def _delete_subscription(self, telegram_user_id: int) -> None:
        try:
            await self._api_client.delete_weekly_subscription(telegram_user_id)
        except SkillraApiError as exc:
            if exc.status_code == 404:
                return
            logger.exception("Failed to delete weekly subscription", extra={"user_id": mask_user_id(telegram_user_id)})
        except Exception:  # noqa: BLE001
            logger.exception("Failed to delete weekly subscription", extra={"user_id": mask_user_id(telegram_user_id)})

    async def _ack_subscription(
        self,
        telegram_user_id: int,
        lock: str,
        sent: bool,
        text_preview: str | None = None,
    ) -> None:
        try:
            kwargs = {"sent": sent}
            if text_preview is not None:
                kwargs["text_preview"] = text_preview
            await self._api_client.ack_weekly_digest_subscription(telegram_user_id, lock, **kwargs)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to acknowledge subscription",
                extra={"user_id": mask_user_id(telegram_user_id), "sent": sent},
            )
            self._increment_metric("ack_failed_total")

    def _write_heartbeat(self) -> None:
        if not self._heartbeat_path:
            return
        write_heartbeat(self._heartbeat_path)

    def _record_tick(self) -> None:
        self._metric_values["last_tick_timestamp_seconds"] = int(time.time())
        self._write_metrics()

    def _increment_metric(self, name: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        self._metric_values[name] = self._metric_values.get(name, 0) + amount
        self._write_metrics()

    def _write_metrics(self) -> None:
        if not self._metrics_path:
            return
        write_worker_metrics(self._metrics_path, self._metric_values)


async def run_worker(api_settings: SkillraApiSettings, bot_token: str, poll_interval: float) -> None:
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    async with SkillraApiClient(api_settings) as api_client:
        worker = DigestWorker(
            bot,
            api_client,
            poll_interval=poll_interval,
            heartbeat_path=os.getenv("DIGEST_WORKER_HEARTBEAT_PATH", DEFAULT_HEARTBEAT_PATH),
        )
        try:
            await worker.run()
        finally:
            await bot.session.close()


async def main() -> None:
    setup_logging(os.getenv("LOG_LEVEL", "INFO").upper(), log_format=os.getenv("LOG_FORMAT", "kv"))
    api_settings = SkillraApiSettings(
        base_url=_require_env("SKILLRA_API_BASE_URL"),
        token=_require_env("SKILLRA_API_TOKEN"),
        admin_token=_require_env("SKILLRA_ADMIN_TOKEN"),
        connect_timeout=_get_float_env("SKILLRA_API_CONNECT_TIMEOUT", 5.0),
        read_timeout=_get_float_env("SKILLRA_API_READ_TIMEOUT", 15.0),
        max_retries=_get_int_env("SKILLRA_API_MAX_RETRIES", 2),
        retry_backoff_seconds=_get_float_env("SKILLRA_API_RETRY_BACKOFF_SECONDS", 0.5),
    )
    await run_worker(api_settings, _require_env("TELEGRAM_BOT_TOKEN"), _get_float_env("DIGEST_POLL_INTERVAL", 60.0))


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        raise SettingsError(f"{key} is required")
    return value


def _get_float_env(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SettingsError(f"{key} must be a float") from exc
    if parsed <= 0:
        raise SettingsError(f"{key} must be positive")
    return parsed


def _get_int_env(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SettingsError(f"{key} must be an integer") from exc


def write_heartbeat(path: str, *, timestamp: float | None = None) -> None:
    """Write the worker heartbeat timestamp used by container healthchecks."""

    heartbeat_path = Path(path)
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(str(timestamp if timestamp is not None else time.time()), encoding="utf-8")


def write_worker_metrics(path: str, values: dict[str, int]) -> None:
    """Write digest-worker counters in node-exporter textfile format."""

    metrics_path = Path(path)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# HELP skillra_digest_worker_claimed_total Subscriptions claimed by the digest worker.",
        "# TYPE skillra_digest_worker_claimed_total counter",
        f"skillra_digest_worker_claimed_total {int(values.get('claimed_total', 0))}",
        "# HELP skillra_digest_worker_sent_total Digest messages sent by the digest worker.",
        "# TYPE skillra_digest_worker_sent_total counter",
        f"skillra_digest_worker_sent_total {int(values.get('sent_total', 0))}",
        "# HELP skillra_digest_worker_failed_total Digest deliveries failed before successful send.",
        "# TYPE skillra_digest_worker_failed_total counter",
        f"skillra_digest_worker_failed_total {int(values.get('failed_total', 0))}",
        "# HELP skillra_digest_worker_ack_failed_total Digest subscription acknowledgements failed.",
        "# TYPE skillra_digest_worker_ack_failed_total counter",
        f"skillra_digest_worker_ack_failed_total {int(values.get('ack_failed_total', 0))}",
        "# HELP skillra_digest_worker_last_tick_timestamp_seconds Unix timestamp of the last worker tick.",
        "# TYPE skillra_digest_worker_last_tick_timestamp_seconds gauge",
        f"skillra_digest_worker_last_tick_timestamp_seconds {int(values.get('last_tick_timestamp_seconds', 0))}",
        "",
    ]
    tmp_path = metrics_path.with_suffix(metrics_path.suffix + ".tmp")
    tmp_path.write_text("\n".join(lines), encoding="utf-8")
    tmp_path.replace(metrics_path)


def heartbeat_is_fresh(path: str, max_age_seconds: float, *, now: float | None = None) -> bool:
    """Return whether the heartbeat file exists and is fresh enough."""

    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
        timestamp = float(raw)
    except (OSError, ValueError):
        return False
    return (now if now is not None else time.time()) - timestamp < max_age_seconds
