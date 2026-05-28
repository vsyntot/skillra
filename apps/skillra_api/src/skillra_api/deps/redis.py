"""Redis dependency for Skillra API (Sprint-006 TASK-05)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Request

logger = logging.getLogger(__name__)


async def get_redis(request: Request) -> Optional[Any]:
    """Return the Redis client from application state (or None if not configured)."""
    return getattr(request.app.state, "redis", None)
