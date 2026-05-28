from __future__ import annotations

import logging

import pytest
from telegram_bot.config import Settings, SettingsError, _get_log_format
from telegram_bot.logging_config import setup_logging


def test_get_log_format_accepts_json() -> None:
    assert _get_log_format("JSON") == "json"


def test_get_log_format_rejects_invalid() -> None:
    with pytest.raises(SettingsError):
        _get_log_format("plain")


def test_settings_reads_log_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("BOT_MODE", "polling")
    monkeypatch.setenv("SKILLRA_API_BASE_URL", "http://api")
    monkeypatch.setenv("SKILLRA_API_TOKEN", "api-token")
    monkeypatch.setenv("SKILLRA_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("LOG_FORMAT", "json")

    settings = Settings.from_env()

    assert settings.log_format == "json"


def test_redacts_admin_token(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    admin_token = "admin-secret-token"
    monkeypatch.setenv("SKILLRA_ADMIN_TOKEN", admin_token)

    root_logger = logging.getLogger()
    previous_filters = list(root_logger.filters)
    previous_handler_filters = [list(handler.filters) for handler in root_logger.handlers]
    setup_logging(level="INFO")

    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("telegram_bot.tests").info("token=%s", admin_token)
    finally:
        root_logger.filters = previous_filters
        for handler, filters in zip(root_logger.handlers, previous_handler_filters, strict=False):
            handler.filters = filters

    assert admin_token not in caplog.text
    assert "***" in caplog.text
