"""Logging middleware for aiogram updates without PII."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from telegram_bot.logging_config import log_extra
from telegram_bot.logging_utils import mask_user_id

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        trace_id = uuid.uuid4().hex
        user_mask = mask_user_id(getattr(getattr(event, "from_user", None), "id", None))
        logger.info(
            "Incoming update",
            **log_extra(trace_id=trace_id, user=user_mask, update_type=event.__class__.__name__),
        )
        data["trace_id"] = trace_id
        return await handler(event, data)


__all__ = ["LoggingMiddleware"]
