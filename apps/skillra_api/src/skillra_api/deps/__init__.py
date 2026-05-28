from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from skillra_api.config import Settings
from skillra_api.datastore import DataStore


def get_settings_dependency(request: Request) -> Settings:  # pragma: no cover - trivial accessor
    return request.app.state.settings


def get_datastore_dependency(request: Request) -> DataStore:  # pragma: no cover - trivial accessor
    return request.app.state.datastore


def get_session_maker_dependency(request: Request) -> async_sessionmaker[AsyncSession]:
    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "DATABASE_UNAVAILABLE",
                "message": "Database is not configured. Set DATABASE_URL.",
                "details": {},
            },
        )
    return session_maker


async def get_db_session(
    session_maker: async_sessionmaker[AsyncSession] = Depends(get_session_maker_dependency),
):
    async with session_maker() as session:
        yield session


def get_redis_dependency(request: Request):  # pragma: no cover - trivial accessor
    """Return Redis client from app state or None if not configured (Sprint-006 TASK-05)."""
    return getattr(request.app.state, "redis", None)
