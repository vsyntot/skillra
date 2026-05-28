"""Simple per-user rate limiting middleware."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

_STALE_CLEANUP_MULTIPLIER = 1000


class RateLimitMiddleware(BaseMiddleware):
    """Per-user rate limiter for Telegram bot handlers.

    .. note::
        No ``asyncio.Lock`` is used here intentionally.  The asyncio event loop is
        single-threaded: all code between two ``await`` checkpoints executes atomically.
        The ``_last_seen`` dict read-check-write sequence contains no ``await`` points,
        so no concurrent mutation is possible (see ADR-002 / GAP-03).
    """

    def __init__(self, rate_limit_per_second: float = 1.0):
        super().__init__()
        self._min_interval = 1.0 / rate_limit_per_second if rate_limit_per_second else 0
        self._last_seen: dict[int, float] = {}
        self._calls_since_cleanup: int = 0
        self._cleanup_threshold: int = max(1, int(_STALE_CLEANUP_MULTIPLIER * self._min_interval))

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()

        # No lock needed: read-check-write has no await between them → atomic in asyncio.
        last = self._last_seen.get(user_id)
        if last is not None and now - last < self._min_interval:
            throttle_message = "Слишком много запросов. Попробуйте ещё раз через пару секунд."
            sender = getattr(event, "answer", None)
            if callable(sender):
                await sender(throttle_message)
            return None

        self._last_seen[user_id] = now
        self._calls_since_cleanup += 1

        # Periodically prune stale entries to prevent unbounded memory growth.
        if self._calls_since_cleanup >= self._cleanup_threshold:
            self._prune_stale(now)
            self._calls_since_cleanup = 0

        return await handler(event, data)

    def _prune_stale(self, now: float) -> None:
        """Remove entries not seen within the last ``_min_interval`` seconds."""
        stale_cutoff = now - max(self._min_interval, 1.0)
        stale = [uid for uid, ts in self._last_seen.items() if ts < stale_cutoff]
        for uid in stale:
            del self._last_seen[uid]
