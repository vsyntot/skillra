import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from telegram_bot.services.meta_cache import MetaCache


def test_cache_hit_returns_cached_value() -> None:
    api_client = AsyncMock()
    api_client.list_roles.return_value = ["role1"]
    cache = MetaCache(ttl_seconds=600)

    asyncio.run(cache.get_roles(api_client))
    api_client.list_roles.assert_awaited_once()

    api_client.list_roles.reset_mock()

    result = asyncio.run(cache.get_roles(api_client))

    assert result == ["role1"]
    api_client.list_roles.assert_not_awaited()


def test_cache_miss_calls_api_again_after_ttl() -> None:
    api_client = AsyncMock()
    api_client.list_roles.side_effect = [["first"], ["second"]]
    cache = MetaCache(ttl_seconds=0)

    first = asyncio.run(cache.get_roles(api_client))
    second = asyncio.run(cache.get_roles(api_client))

    assert first == ["first"]
    assert second == ["second"]
    assert api_client.list_roles.await_count == 2


def test_returns_stale_cache_on_error(caplog: pytest.LogCaptureFixture) -> None:
    api_client = AsyncMock()
    api_client.list_roles.return_value = ["cached"]
    cache = MetaCache(ttl_seconds=0)

    asyncio.run(cache.get_roles(api_client))
    api_client.list_roles.side_effect = RuntimeError("api down")

    caplog.set_level(logging.WARNING)

    result = asyncio.run(cache.get_roles(api_client))

    assert result == ["cached"]
    assert "Using stale roles cache" in caplog.text
