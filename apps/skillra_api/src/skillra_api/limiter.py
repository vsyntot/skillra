from __future__ import annotations

from typing import Any, Callable, TypeVar

from skillra_api.config import get_settings
from skillra_api.middlewares.rate_limit_key import rate_limit_key

try:
    from slowapi import Limiter
except ModuleNotFoundError:  # pragma: no cover
    Limiter = None  # type: ignore[assignment,misc]

F = TypeVar("F", bound=Callable[..., Any])


class _NoopLimiter:
    def limit(self, _limit_value: str) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            return func

        return decorator


settings = get_settings()
limiter = Limiter(key_func=rate_limit_key, default_limits=[settings.rate_limit_default]) if Limiter else _NoopLimiter()
