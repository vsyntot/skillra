"""Logging helpers for the Telegram bot."""

from __future__ import annotations

import json
import logging
import os
from typing import Any


class _RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - side-effect only
        if not self._secrets:
            return True

        message = record.getMessage()
        for secret in self._secrets:
            message = message.replace(secret, "***")

        record.msg = message
        record.args = None
        return True


def setup_logging(level: str = "INFO", *, log_format: str = "kv") -> None:
    """Configure structured logging baseline.

    We avoid logging PII (message text, usernames) and prefer key=value format.
    """

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    if log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logging.basicConfig(level=numeric_level, handlers=[handler])
    else:
        logging.basicConfig(
            level=numeric_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    secrets = [
        os.getenv("TELEGRAM_BOT_TOKEN", ""),
        os.getenv("SKILLRA_API_TOKEN", ""),
        os.getenv("SKILLRA_ADMIN_TOKEN", ""),
        os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", ""),
    ]
    redacting_filter = _RedactingFilter(secrets)
    root_logger = logging.getLogger()
    root_logger.addFilter(redacting_filter)
    for handler in root_logger.handlers:
        handler.addFilter(redacting_filter)


def log_extra(**fields: Any) -> dict[str, Any]:
    """Helper to attach structured fields to logs."""

    return {"extra": {"context": fields}}


class _JsonFormatter(logging.Formatter):
    """Render log records as JSON strings."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting helper
        payload = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)
