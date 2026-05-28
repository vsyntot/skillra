from __future__ import annotations

import pytest
from telegram_bot.config import Settings, SettingsError


def _set_common_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setenv("SKILLRA_API_TOKEN", "token")
    monkeypatch.setenv("SKILLRA_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "")


def test_official_bot_can_run_only_in_prod_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("SKILLRA_RUNTIME_ENV", "local")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "skillra_bot")
    monkeypatch.setenv("SKILLRA_API_BASE_URL", "http://prod-skillra-api:8000")

    with pytest.raises(SettingsError, match="production bot"):
        Settings.from_env()


def test_official_bot_rejects_local_api_even_in_prod_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("SKILLRA_RUNTIME_ENV", "prod")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@skillra_bot")
    monkeypatch.setenv("SKILLRA_API_BASE_URL", "http://localhost:8000")

    with pytest.raises(SettingsError, match="local SKILLRA_API_BASE_URL"):
        Settings.from_env()


def test_official_bot_accepts_prod_runtime_internal_api(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("SKILLRA_RUNTIME_ENV", "prod")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "skillra_bot")
    monkeypatch.setenv("SKILLRA_API_BASE_URL", "http://prod-skillra-api:8000")

    settings = Settings.from_env()

    assert settings.runtime_env == "prod"
    assert settings.bot.username == "skillra_bot"
    assert settings.api.base_url == "http://prod-skillra-api:8000"


def test_dev_bot_accepts_local_api(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_common_env(monkeypatch)
    monkeypatch.setenv("SKILLRA_RUNTIME_ENV", "local")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "skillra_dev_bot")
    monkeypatch.setenv("SKILLRA_API_BASE_URL", "http://localhost:8000")

    settings = Settings.from_env()

    assert settings.runtime_env == "local"
    assert settings.bot.username == "skillra_dev_bot"
