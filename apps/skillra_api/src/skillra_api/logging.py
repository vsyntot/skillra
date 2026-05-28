"""Logging utilities for Skillra API."""

from __future__ import annotations

import json
import logging
import os
from typing import Iterable

DEFAULT_LOG_FORMAT = "time=%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s"

JSON_LOG_FORMAT = {
    "time": "%(asctime)s",
    "level": "%(levelname)s",
    "logger": "%(name)s",
    "message": "%(message)s",
}


def configure_logging(level: str = "INFO", *, log_format: str = "kv") -> None:
    """Configure application logging with a structured format.

    Parameters
    ----------
    level:
        Desired log level name (e.g., "INFO", "DEBUG").
    log_format:
        Either ``"json"`` for JSON logs or ``"kv"`` for key=value logs.
    """

    numeric_level = logging.getLevelName(level.upper())

    if log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter(JSON_LOG_FORMAT))
        logging.basicConfig(level=numeric_level, handlers=[handler])
    else:
        logging.basicConfig(level=numeric_level, format=DEFAULT_LOG_FORMAT)

    secrets = [
        os.getenv("SKILLRA_API_TOKEN", ""),
        os.getenv("SKILLRA_ADMIN_TOKEN", ""),
        os.getenv("TELEGRAM_BOT_TOKEN", ""),
    ]
    redacting_filter = _TokenRedactingFilter(secrets)

    root_logger = logging.getLogger()
    root_logger.addFilter(redacting_filter)

    # Apply same level/filter to uvicorn loggers.
    # NOTE: Keep uvicorn.access compatible with its AccessFormatter.
    for logger_name in _uvicorn_logger_names():
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.setLevel(numeric_level)
        uvicorn_logger.addFilter(redacting_filter)


def _uvicorn_logger_names() -> Iterable[str]:
    """Return uvicorn logger names that should inherit the application level."""
    return ("uvicorn", "uvicorn.error", "uvicorn.access")


class _TokenRedactingFilter(logging.Filter):
    """Filter that redacts sensitive tokens from log messages.

    IMPORTANT:
    - Do NOT set record.args = None.
      Uvicorn access logger expects args to be tuple-like; None breaks its formatter.
    - If we override msg with a fully rendered string, set args to empty tuple.
    """

    def __init__(self, secrets: Iterable[str]):
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - side-effect only
        if not self._secrets:
            return True

        # Get rendered message once, then redact tokens in it.
        message = record.getMessage()
        original = message

        for secret in self._secrets:
            message = message.replace(secret, "***")

        # If nothing changed, keep record untouched.
        if message == original:
            return True

        # Replace message with redacted string.
        # Set args to empty tuple to avoid formatter issues (e.g., uvicorn.access).
        record.msg = message
        record.args = ()
        return True


class _JsonFormatter(logging.Formatter):
    """Render log records as JSON strings."""

    def __init__(self, template: dict[str, str]):
        super().__init__()
        self._template = template

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting helper
        payload = {field: self._format_value(value, record) for field, value in self._template.items()}
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)

    def _format_value(self, value: str, record: logging.LogRecord) -> str:
        formatter = logging.Formatter(value)
        return formatter.format(record)
