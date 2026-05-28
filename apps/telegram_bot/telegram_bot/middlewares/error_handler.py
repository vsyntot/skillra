"""Catch-all error handling middleware."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from telegram_bot.logging_config import log_extra

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseMiddleware):
    def __init__(self, fallback_text: str):
        super().__init__()
        self.fallback_text = fallback_text

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:  # noqa: BLE001
            trace_id = data.get("trace_id")
            logger.exception(
                "Unhandled error while processing update",
                **log_extra(trace_id=trace_id, error_type=exc.__class__.__name__),
            )
            sender = getattr(event, "answer", None)
            if callable(sender):
                await sender(self.fallback_text)
            return None
