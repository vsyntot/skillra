"""Persona share-token storage with Redis primary and DB fallback."""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from skillra_api.db.models import ShareToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def create_share(
    payload: dict[str, Any],
    *,
    redis: Any | None = None,
    session: AsyncSession | None = None,
    ttl_days: int = 7,
) -> str:
    """Create a share token in Redis, falling back to DB when Redis is unavailable."""

    token = secrets.token_urlsafe(32)
    payload_json = json.dumps(payload)
    ttl_seconds = ttl_days * 86400

    if redis is not None:
        try:
            if hasattr(redis, "setex"):
                await redis.setex(f"share:{token}", ttl_seconds, payload_json)
            else:
                await redis.set(f"share:{token}", payload_json, ex=ttl_seconds)
            return token
        except Exception:  # noqa: BLE001
            logger.warning("Redis unavailable for share create - falling back to DB")

    if session is None:
        raise RuntimeError("Database session is required for share fallback")

    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    async with session.begin():
        session.add(ShareToken(token=token, payload=payload_json, expires_at=expires_at))
    return token


async def get_share(
    token: str,
    *,
    redis: Any | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """Read a share token from Redis, falling back to DB when Redis misses or fails."""

    if redis is not None:
        try:
            raw = await redis.get(f"share:{token}")
            if raw:
                return json.loads(raw)
        except Exception:  # noqa: BLE001
            logger.warning("Redis unavailable for share read - trying DB")

    if session is None:
        return None

    now = datetime.now(timezone.utc)
    row = await session.scalar(select(ShareToken).where(ShareToken.token == token, ShareToken.expires_at > now))
    return json.loads(row.payload) if row is not None else None
