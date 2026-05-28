from __future__ import annotations

# Force non-interactive matplotlib backend before any pyplot imports.
# This is required for thread-pool rendering (asyncio.to_thread) on macOS and
# headless Linux servers. Must be set before skillra_pda.personas is imported.
# See ADR-002 and https://matplotlib.org/stable/users/explain/figure/backends.html
import asyncio
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
except ModuleNotFoundError:  # pragma: no cover - optional dependency may be absent in minimal envs
    sentry_sdk = None
    FastApiIntegration = None

try:
    import redis.asyncio as aioredis
except ModuleNotFoundError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

try:
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
except ModuleNotFoundError:  # pragma: no cover
    _rate_limit_exceeded_handler = None  # type: ignore[assignment]
    RateLimitExceeded = None  # type: ignore[assignment,misc]

from skillra_api.config import Settings, get_settings
from skillra_api.constants import API_VERSION
from skillra_api.datastore import DataStore
from skillra_api.db import create_async_engine_from_settings, create_session_maker
from skillra_api.db.models import VacancySnapshot, WeeklySubscription
from skillra_api.error_handlers import (
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from skillra_api.limiter import limiter
from skillra_api.logging import configure_logging
from skillra_api.metrics import ACTIVE_SUBSCRIPTIONS
from skillra_api.middlewares import RequestIDMiddleware, RequestLoggingMiddleware
from skillra_api.routers import (
    admin,
    billing,
    digest,
    digest_history,
    health,
    market,
    meta,
    metrics,
    organizations,
    persona,
    search,
    subscriptions,
    users,
)

logger = logging.getLogger(__name__)


def _parse_cors_origins(value: str) -> list[str]:
    """Parse comma-separated CORS origins from settings."""

    return [origin.strip() for origin in value.split(",") if origin.strip()]


async def _active_subscriptions_gauge_loop(session_maker: async_sessionmaker, interval_seconds: float = 300.0) -> None:
    """Refresh active subscription gauge while the API process is alive."""

    try:
        while True:
            try:
                async with session_maker() as session:
                    count = await session.scalar(
                        select(func.count()).select_from(WeeklySubscription).where(WeeklySubscription.active.is_(True))
                    )
                ACTIVE_SUBSCRIPTIONS.set(int(count or 0))
            except Exception:  # noqa: BLE001
                logger.exception("Failed to refresh active subscription metric")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        raise


async def _auto_seed_if_empty(
    session_maker: async_sessionmaker,
    datastore: DataStore,
    settings: Settings,
) -> None:
    """Seed vacancy_snapshots and MeiliSearch on cold start when the table is empty."""

    from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots_incremental

    try:
        async with session_maker() as session:
            count = await session.scalar(select(func.count()).select_from(VacancySnapshot))
        if (count or 0) > 0:
            logger.info("vacancy_snapshots already populated count=%d - skip auto-seed", count)
            return
        if not datastore.is_ready:
            logger.info("DataStore not ready - skip auto-seed")
            return

        logger.info("vacancy_snapshots empty - starting auto-seed")
        async with session_maker() as session:
            result = await sync_vacancy_snapshots_incremental(session, datastore.get_features_df(), settings)
        logger.info("auto-seed completed inserted=%d indexed=%d", result["inserted"], result["indexed"])
    except Exception:  # noqa: BLE001
        logger.exception("auto-seed failed - search will return empty results")


async def _subscribe_datastore_reload(
    redis: Any,
    datastore: DataStore,
    session_maker: async_sessionmaker | None,
) -> None:
    """Reload the in-process DataStore when another API replica publishes an event."""

    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe("datastore_reload")
        async for message in pubsub.listen():
            if message.get("type") == "message":
                logger.info("Received datastore_reload event")
                await _reload_datastore_from_active_pointer(datastore, session_maker)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("datastore_reload subscriber stopped")
    finally:
        close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


async def _reload_datastore_from_active_pointer(
    datastore: DataStore,
    session_maker: async_sessionmaker | None,
) -> None:
    """Reload DataStore from the active Dataset Registry pointer when available."""

    if session_maker is None:
        await datastore.areload()
        return
    try:
        plan = await admin._active_reload_plan(session_maker)  # noqa: SLF001
    except (admin.ActiveDatasetArtifactError, SQLAlchemyError):  # noqa: SLF001
        logger.exception("Active Dataset Registry pointer is not reloadable; falling back to configured cache paths")
        await datastore.areload()
        return
    if plan is None:
        await datastore.areload()
        return
    await datastore.areload_from_paths(plan.paths)
    served_run_id = (datastore.get_dataset_meta() or {}).get("run_id")
    if str(served_run_id or "") != plan.run_id:
        raise RuntimeError(f"Loaded dataset run {served_run_id!r} does not match active run {plan.run_id!r}.")


async def _check_migrations(engine: AsyncEngine) -> dict[str, Any]:
    """Return Alembic migration state for readiness reporting."""

    try:
        async with engine.connect() as conn:
            current = await conn.run_sync(
                lambda sync_conn: MigrationContext.configure(sync_conn).get_current_revision()
            )

        app_root = Path(__file__).resolve().parents[2]
        alembic_cfg = AlembicConfig(str(app_root / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(app_root / "alembic"))
        script = ScriptDirectory.from_config(alembic_cfg)
        head = script.get_current_head()
        status = "ok" if current == head else "degraded"
        if status == "degraded":
            logger.warning("DB schema behind latest migration current=%s head=%s", current, head)
        return {"status": status, "current": current, "head": head}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to check Alembic migration state")
        return {"status": "error", "current": None, "head": None, "error": str(exc)}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: load parquet data on startup, dispose DB pool on shutdown."""

    app_settings: Settings = app.state.settings

    # Sprint-006 TASK-05: Initialize Redis client
    if aioredis and app_settings.redis_url:
        redis_client = None
        try:
            redis_client = await aioredis.from_url(app_settings.redis_url, decode_responses=True)
            await redis_client.ping()
            app.state.redis = redis_client
            logger.info("Redis connected url=%s", app_settings.redis_url)
        except Exception as exc:  # pragma: no cover
            if redis_client is not None:
                await redis_client.aclose()
            logger.warning("Redis connection failed: %s — proceeding without cache", exc)
            app.state.redis = None
    else:
        app.state.redis = None

    # Sprint-009 TASK-01: Initialize MeiliSearch indexes on startup
    if app_settings.meilisearch_url:
        try:
            from skillra_api.services.search import configure_search_indexes, get_search_client

            meili = await get_search_client(app_settings)
            if meili is None:
                raise RuntimeError("MeiliSearch client is not configured")
            await meili.create_index_if_not_exists("vacancies", primary_key="id")
            await meili.create_index_if_not_exists("skills", primary_key="id")
            await configure_search_indexes(meili)
            app.state.meilisearch_status = "ok"
            logger.info("MeiliSearch indexes initialized")
        except Exception:  # pragma: no cover - optional dependency
            from skillra_api.services.search import close_search_client

            await close_search_client()
            app.state.meilisearch_status = "degraded"
            logger.warning("MeiliSearch index init failed — search will use DB fallback")
    else:
        app.state.meilisearch_status = "not_configured"

    app.state.migration_status = {"status": "not_configured", "current": None, "head": None}
    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        app.state.migration_status = await _check_migrations(engine)

    # Load parquet datasets asynchronously before accepting requests.
    await _reload_datastore_from_active_pointer(app.state.datastore, app.state.session_maker)

    auto_seed_task = None
    if app.state.session_maker is not None:
        auto_seed_task = asyncio.create_task(
            _auto_seed_if_empty(app.state.session_maker, app.state.datastore, app_settings),
            name="auto-seed-meilisearch",
        )

    # Sprint-007 TASK-09: Start DataStore file watch background task
    watch_task = None
    if app_settings.data_watch_interval > 0 and app.state.session_maker is None:
        watch_task = asyncio.create_task(
            app.state.datastore.watch_reload(app_settings.data_watch_interval),
            name="datastore-watch",
        )

    datastore_reload_task = None
    if app.state.redis is not None:
        datastore_reload_task = asyncio.create_task(
            _subscribe_datastore_reload(app.state.redis, app.state.datastore, app.state.session_maker),
            name="datastore-reload-subscriber",
        )

    active_subscriptions_task = None
    if app.state.session_maker is not None:
        active_subscriptions_task = asyncio.create_task(
            _active_subscriptions_gauge_loop(app.state.session_maker),
            name="active-subscriptions-gauge",
        )

    yield

    if watch_task:
        watch_task.cancel()
    if datastore_reload_task:
        datastore_reload_task.cancel()
    if active_subscriptions_task:
        active_subscriptions_task.cancel()
    if auto_seed_task:
        auto_seed_task.cancel()

    # Sprint-006 TASK-05: Close Redis connection
    if app.state.redis:
        await app.state.redis.aclose()

    from skillra_api.services.search import close_search_client

    await close_search_client()

    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level, log_format=app_settings.log_format)

    if app_settings.sentry_dsn:
        if not sentry_sdk or not FastApiIntegration:
            msg = "Sentry SDK must be installed when SENTRY_DSN is configured"
            raise RuntimeError(msg)

        sentry_sdk.init(
            dsn=app_settings.sentry_dsn,
            integrations=[FastApiIntegration()],
            send_default_pii=False,
        )

    application = FastAPI(title=app_settings.app_name, version=API_VERSION, lifespan=_lifespan)
    application.state.settings = app_settings
    application.state.datastore = DataStore(app_settings)

    # Sprint-007 TASK-08: Rate limiting via SlowAPI
    application.state.limiter = limiter
    if RateLimitExceeded and _rate_limit_exceeded_handler:
        application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    application.add_middleware(RequestIDMiddleware)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_parse_cors_origins(app_settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if app_settings.database_url:
        engine = create_async_engine_from_settings(app_settings)
        session_maker = create_session_maker(engine, expire_on_commit=False)
    else:
        engine = None
        session_maker = None

    application.state.db_engine = engine
    application.state.session_maker = session_maker
    application.state.migration_status = {"status": "not_configured", "current": None, "head": None}

    application.include_router(health.router)
    application.include_router(meta.router)
    application.include_router(market.router)
    application.include_router(organizations.router)
    application.include_router(persona.router)
    application.include_router(persona.public_router)
    application.include_router(admin.router)
    application.include_router(billing.router)
    application.include_router(users.auth_router)
    application.include_router(users.router)
    application.include_router(users.admin_router)
    application.include_router(subscriptions.router)
    application.include_router(digest.router)
    application.include_router(digest_history.router)
    application.include_router(search.router)
    application.include_router(metrics.router)

    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, generic_exception_handler)

    return application


app = create_app()
