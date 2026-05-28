"""TTL cache for Skillra meta endpoints."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from telegram_bot.services.api_client import SkillraApiClient

logger = logging.getLogger(__name__)


class MetaCache:
    """Cache meta values with TTL to reduce API calls."""

    def __init__(self, ttl_seconds: int = 600):
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, list[str]]] = {}

    async def get_roles(self, api_client: SkillraApiClient) -> list[str]:
        return await self._get_meta("roles", api_client.list_roles)

    async def get_grades(self, api_client: SkillraApiClient) -> list[str]:
        return await self._get_meta("grades", api_client.list_grades)

    async def get_city_tiers(self, api_client: SkillraApiClient) -> list[str]:
        return await self._get_meta("city_tiers", api_client.list_city_tiers)

    async def get_work_modes(self, api_client: SkillraApiClient) -> list[str]:
        return await self._get_meta("work_modes", api_client.list_work_modes)

    async def get_domains(self, api_client: SkillraApiClient) -> list[str]:
        return await self._get_meta("domains", api_client.list_domains)

    async def get_skills(self, api_client: SkillraApiClient) -> list[str]:
        return await self._get_meta("skills", api_client.list_skills)

    async def _get_meta(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[list[str]]],
    ) -> list[str]:
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and self._is_valid(cached[0], now):
            return cached[1]

        try:
            value = await fetcher()
        except Exception:  # noqa: BLE001
            if cached:
                logger.warning("Using stale %s cache due to API error", key, exc_info=True)
                return cached[1]
            raise

        self._cache[key] = (now, value)
        return value

    def _is_valid(self, updated_at: float, now: float | None = None) -> bool:
        current_time = now or time.monotonic()
        return current_time - updated_at < self._ttl_seconds
