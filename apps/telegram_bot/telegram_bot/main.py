"""Entry point for the Skillra Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommandScopeAllPrivateChats, BotCommandScopeChat
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

from telegram_bot.config import Settings, SettingsError, WebhookSettings
from telegram_bot.handlers import admin, analytics, api_key, commands, onboarding, pdf_report, search, subscriptions
from telegram_bot.logging_config import setup_logging
from telegram_bot.middlewares.error_handler import ErrorHandlingMiddleware
from telegram_bot.middlewares.logging import LoggingMiddleware
from telegram_bot.middlewares.rate_limit import RateLimitMiddleware
from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.callback_context import CallbackContextStore
from telegram_bot.services.meta_cache import MetaCache

logger = logging.getLogger(__name__)
ADMIN_IDS_KEY = web.AppKey("admin_ids", set[int])
BOT_KEY = web.AppKey("bot", Bot)


async def run() -> None:
    """Spin up polling bot with basic middlewares and routers."""

    load_dotenv(override=False)
    config = Settings.from_env()
    setup_logging(config.log_level, log_format=config.log_format)

    _configure_sentry(os.getenv("SENTRY_DSN"))

    # NOTE: aiogram >= 3.7.0 removed parse_mode/disable_web_page_preview/protect_content from Bot initializer.
    # Use DefaultBotProperties instead.
    bot = Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode(config.bot.parse_mode)),
    )
    dp = Dispatcher(storage=_build_storage(config))

    dp.update.middleware(LoggingMiddleware())
    dp.update.middleware(ErrorHandlingMiddleware(fallback_text="Что-то пошло не так. Попробуйте позже."))
    dp.message.middleware(RateLimitMiddleware(rate_limit_per_second=config.bot.rate_limit_per_second))

    dp.include_router(commands.router)
    dp.include_router(api_key.router)
    dp.include_router(admin.router)
    dp.include_router(analytics.router)
    dp.include_router(search.router)
    dp.include_router(pdf_report.router)
    dp.include_router(onboarding.router)
    dp.include_router(subscriptions.router)

    _register_lifecycle_events(dp, bot, config)

    # B-NEW-03 fix: Start market_update_listener for BOTH polling and webhook modes
    # Sprint-009 TASK-07: Redis pub/sub listener for market data updates
    market_listener_task = None
    try:
        market_listener_task = asyncio.create_task(
            market_update_listener(bot, config.redis.url, config.api),
            name="market-update-listener",
        )
    except Exception:  # noqa: BLE001
        logger.warning("Could not start market_update_listener background task")

    if config.bot.mode == "webhook":
        if not config.webhook:
            raise SettingsError("Webhook settings are required in webhook mode")
        try:
            await _run_webhook(bot, dp, config.webhook, admin_ids=set(config.bot.admin_ids or []))
        finally:
            if market_listener_task:
                market_listener_task.cancel()
                try:
                    await market_listener_task
                except (asyncio.CancelledError, Exception):
                    pass
        return

    logger.info("Starting Skillra Telegram Bot (polling mode)")
    alert_runner = await _start_alert_receiver(bot, admin_ids=set(config.bot.admin_ids or []))
    try:
        await dp.start_polling(bot)
    finally:
        await alert_runner.cleanup()
        if market_listener_task:
            market_listener_task.cancel()
            try:
                await market_listener_task
            except (asyncio.CancelledError, Exception):
                pass


def _build_storage(config: Settings):
    try:
        from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage
    except ModuleNotFoundError:  # pragma: no cover - optional dependency for tests
        RedisStorage = None  # type: ignore[assignment]
        DefaultKeyBuilder = None  # type: ignore[assignment]

    if RedisStorage and DefaultKeyBuilder:
        return RedisStorage.from_url(config.redis.url, key_builder=DefaultKeyBuilder(with_bot_id=True))

    logger.warning("Redis storage unavailable, falling back to in-memory FSM.")
    return MemoryStorage()


def _register_lifecycle_events(dp: Dispatcher, bot: Bot, config: Settings) -> None:
    api_client = SkillraApiClient(config.api)
    meta_cache = MetaCache()
    callback_context = CallbackContextStore(redis_url=config.redis.url, signing_secret=config.bot.token)

    async def on_startup() -> None:
        dp.workflow_data["api_client"] = api_client
        dp.workflow_data["meta_cache"] = meta_cache
        dp.workflow_data["digest_settings"] = config.digest
        dp.workflow_data["callback_context"] = callback_context

        admin_ids = set(config.bot.admin_ids or [])
        dp.workflow_data["admin_ids"] = admin_ids

        await callback_context.connect()
        await api_client.__aenter__()
        await _set_bot_commands(bot, admin_ids)

    async def on_shutdown() -> None:
        await api_client.__aexit__(None, None, None)
        await callback_context.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)


async def _run_webhook(bot: Bot, dp: Dispatcher, webhook: WebhookSettings, admin_ids: set[int] | None = None) -> None:
    logger.info(
        "Starting Skillra Telegram Bot (webhook mode)",
        extra={"url": webhook.url, "host": webhook.host, "port": webhook.port},
    )

    app = _create_webhook_application(bot, dp, webhook, admin_ids=admin_ids)
    runner = web.AppRunner(app)
    await runner.setup()

    await bot.set_webhook(
        url=webhook.url,
        secret_token=webhook.secret_token,
        drop_pending_updates=webhook.drop_pending_updates,
    )

    site = web.TCPSite(runner, host=webhook.host, port=webhook.port)
    await site.start()

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("Webhook runner cancelled")
        raise
    finally:
        if webhook.delete_webhook_on_shutdown:
            await bot.delete_webhook(drop_pending_updates=False)
        await runner.cleanup()


def _create_webhook_application(
    bot: Bot,
    dp: Dispatcher,
    webhook: WebhookSettings,
    admin_ids: set[int] | None = None,
) -> web.Application:
    app = web.Application()
    _register_alert_receiver(app, bot, admin_ids=admin_ids)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=webhook.secret_token).register(app, path=webhook.path)
    setup_application(app, dp, bot=bot)

    return app


def _create_alert_receiver_application(bot: Bot, admin_ids: set[int] | None = None) -> web.Application:
    app = web.Application()
    _register_alert_receiver(app, bot, admin_ids=admin_ids)
    return app


def _register_alert_receiver(app: web.Application, bot: Bot, admin_ids: set[int] | None = None) -> None:
    app[BOT_KEY] = bot
    app[ADMIN_IDS_KEY] = admin_ids or set()

    async def _healthcheck(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _alerts(request: web.Request) -> web.Response:
        payload = await request.json()
        alerts = payload.get("alerts", []) if isinstance(payload, dict) else []
        lines = ["<b>Skillra alert</b>"]
        for alert in alerts[:5]:
            labels = alert.get("labels", {}) if isinstance(alert, dict) else {}
            annotations = alert.get("annotations", {}) if isinstance(alert, dict) else {}
            status = alert.get("status", "firing") if isinstance(alert, dict) else "firing"
            name = labels.get("alertname", "unknown")
            summary = annotations.get("summary") or annotations.get("description") or ""
            lines.append(f"{status}: {name} {summary}".strip())

        for admin_id in app[ADMIN_IDS_KEY]:
            await bot.send_message(admin_id, "\n".join(lines))
        return web.json_response({"status": "ok", "alerts": len(alerts)})

    app.router.add_get("/health", _healthcheck)
    app.router.add_post("/alerts", _alerts)


async def _start_alert_receiver(bot: Bot, admin_ids: set[int]) -> web.AppRunner:
    host = os.getenv("TELEGRAM_WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8080"))
    app = _create_alert_receiver_application(bot, admin_ids=admin_ids)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("Started Skillra alert receiver", extra={"host": host, "port": port})
    return runner


async def _set_bot_commands(bot: Bot, admin_ids: set[int]) -> None:
    await bot.set_my_commands(commands.build_bot_commands(), scope=BotCommandScopeAllPrivateChats())

    admin_commands = commands.build_bot_commands(include_admin=True)
    for admin_id in admin_ids:
        await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))


def _configure_sentry(sentry_dsn: str | None) -> None:
    if not sentry_dsn:
        return

    try:
        import sentry_sdk
    except ModuleNotFoundError:  # pragma: no cover - sentry is optional for local runs
        msg = "Sentry SDK must be installed when SENTRY_DSN is configured"
        raise RuntimeError(msg)

    sentry_sdk.init(dsn=sentry_dsn, send_default_pii=False)


def main() -> None:
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Sprint-009 TASK-07: market_update_listener — Redis pub/sub background task
# ---------------------------------------------------------------------------


async def market_update_listener(bot: Bot, redis_url: str, api_settings: "SkillraApiSettings") -> None:  # type: ignore[name-defined]
    """Listen to 'market_updated' Redis channel and notify active subscribers.

    De-duplication: sends at most 1 broadcast per 24 hours via Redis key with TTL.
    """
    try:
        import redis.asyncio as aioredis
    except ModuleNotFoundError:  # pragma: no cover
        logger.warning("redis.asyncio not available — market_update_listener disabled")
        return

    DEDUP_KEY = "market_updated:last_notified"
    DEDUP_TTL = 86400  # 24 hours

    r = await aioredis.from_url(redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("market_updated")
    logger.info("market_update_listener: subscribed to Redis channel 'market_updated'")

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            # De-duplicate: skip if already notified in the past 24h
            already_notified = await r.exists(DEDUP_KEY)
            if already_notified:
                logger.debug("market_update_listener: skipping duplicate notification")
                continue

            await r.set(DEDUP_KEY, "1", ex=DEDUP_TTL)
            logger.info("market_update_listener: broadcasting market update to subscribers")

            try:
                async with SkillraApiClient(api_settings) as client:
                    subs = await client.get_active_subscribers()
                    sent = 0
                    for sub in subs:
                        tg_id = sub.get("telegram_user_id")
                        if not tg_id:
                            continue
                        try:
                            await bot.send_message(
                                tg_id,
                                "📊 <b>Данные рынка обновились!</b>\n\n"
                                "Свежий анализ доступен по команде /skillgap или /digest.",
                                parse_mode="HTML",
                            )
                            sent += 1
                            await asyncio.sleep(0.05)  # Telegram rate limit
                        except Exception:  # noqa: BLE001
                            pass
                logger.info("market_update_listener: sent to %d subscribers", sent)
            except Exception:  # noqa: BLE001
                logger.exception("market_update_listener: failed to notify subscribers")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("market_update_listener: unexpected error")
    finally:
        await pubsub.unsubscribe("market_updated")
        await r.aclose()


from telegram_bot.config import SkillraApiSettings  # noqa: E402 (used in type hint above)

if __name__ == "__main__":
    main()
