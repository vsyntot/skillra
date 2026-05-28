"""Retry wrapper for transient external dependency failures."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

logger = logging.getLogger(__name__)
T = TypeVar("T")

try:
    from tenacity import (  # type: ignore[import-untyped]
        before_sleep_log,
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )
except ModuleNotFoundError:  # pragma: no cover - keeps tests runnable in minimal local envs
    before_sleep_log = None
    retry = None
    retry_if_exception_type = None
    stop_after_attempt = None
    wait_exponential = None


def with_retry(
    *exception_types: type[Exception],
    max_attempts: int = 3,
    wait_min: float = 0.5,
    wait_max: float = 10.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Retry an async callable on transient exceptions with exponential backoff."""

    retry_exceptions = exception_types or (Exception,)

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        if retry is not None:
            return cast(
                Callable[..., Awaitable[T]],
                retry(
                    retry=retry_if_exception_type(retry_exceptions),
                    stop=stop_after_attempt(max_attempts),
                    wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
                    before_sleep=before_sleep_log(logger, logging.WARNING),
                    reraise=True,
                )(func),
            )

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            attempt = 0
            delay = wait_min
            while True:
                attempt += 1
                try:
                    return await func(*args, **kwargs)
                except retry_exceptions:
                    if attempt >= max_attempts:
                        raise
                    logger.warning("Transient failure in %s; retrying attempt=%d", func.__name__, attempt + 1)
                    await asyncio.sleep(min(delay, wait_max))
                    delay = min(delay * 2, wait_max)

        return wrapper

    return decorator
