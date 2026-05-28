"""Redis-backed cache helpers for metadata endpoints."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")
META_TTL = 300


async def _setex(redis: Any, key: str, ttl: int, value: str) -> None:
    if hasattr(redis, "setex"):
        await redis.setex(key, ttl, value)
    else:
        await redis.set(key, value, ex=ttl)


async def cached_meta(
    redis: Any | None,
    key: str,
    loader: Callable[[], T] | Callable[[], Awaitable[T]],
) -> T:
    """Return cached metadata, falling back to loader if Redis is absent or unavailable."""

    cache_key = f"meta:{key}"
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:  # noqa: BLE001
            redis = None

    result = loader()
    if hasattr(result, "__await__"):
        result = await result  # type: ignore[assignment]

    if redis is not None:
        try:
            await _setex(redis, cache_key, META_TTL, json.dumps(result))
        except Exception:  # noqa: BLE001
            pass
    return result  # type: ignore[return-value]
