"""Configuration parsing for the Telegram bot."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from aiogram.enums import ParseMode

OFFICIAL_BOT_USERNAME = "skillra_bot"
LOCAL_API_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}


class SettingsError(ValueError):
    """Raised when the environment configuration is invalid."""


@dataclass
class BotSettings:
    token: str
    username: str | None = None
    official_username: str = OFFICIAL_BOT_USERNAME
    mode: str = "polling"
    parse_mode: str = "HTML"
    rate_limit_per_second: float = 1.0
    digest_poll_interval_seconds: float = 60.0
    admin_ids: list[int] | None = None

    def __post_init__(self) -> None:
        if not self.token:
            raise SettingsError("TELEGRAM_BOT_TOKEN is required")
        self.username = _normalize_bot_username(self.username)
        self.official_username = _normalize_bot_username(self.official_username) or OFFICIAL_BOT_USERNAME
        if self.rate_limit_per_second <= 0:
            raise SettingsError("TELEGRAM_RATE_LIMIT_PER_SECOND must be positive")
        if self.digest_poll_interval_seconds <= 0:
            raise SettingsError("TELEGRAM_DIGEST_POLL_INTERVAL_SECONDS must be positive")
        if self.mode not in {"polling", "webhook"}:
            raise SettingsError("BOT_MODE must be either 'polling' or 'webhook'")
        try:
            ParseMode(self.parse_mode)
        except ValueError as exc:
            raise SettingsError("TELEGRAM_PARSE_MODE is invalid") from exc

        if self.admin_ids is None:
            self.admin_ids = []
        invalid_ids = [admin_id for admin_id in self.admin_ids if admin_id <= 0]
        if invalid_ids:
            raise SettingsError("TELEGRAM_ADMIN_IDS must contain positive integers")


@dataclass
class SkillraApiSettings:
    base_url: str
    token: str
    admin_token: str
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not self.base_url:
            raise SettingsError("SKILLRA_API_BASE_URL is required")
        if not self.token:
            raise SettingsError("SKILLRA_API_TOKEN is required")
        if not self.admin_token:
            raise SettingsError("SKILLRA_ADMIN_TOKEN is required")
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise SettingsError("Timeouts must be positive")
        if self.max_retries < 0:
            raise SettingsError("SKILLRA_API_MAX_RETRIES cannot be negative")
        if self.retry_backoff_seconds < 0:
            raise SettingsError("SKILLRA_API_RETRY_BACKOFF_SECONDS cannot be negative")


@dataclass
class RedisSettings:
    url: str

    def __post_init__(self) -> None:
        if not self.url:
            raise SettingsError("REDIS_URL is required for FSM storage")


@dataclass
class Settings:
    bot: BotSettings
    api: SkillraApiSettings
    redis: RedisSettings
    digest: "DigestSettings"
    webhook: "WebhookSettings | None" = None
    log_level: str = "INFO"
    log_format: str = "kv"
    runtime_env: str = "local"

    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from environment variables with validation."""

        bot_settings = BotSettings(
            token=_require_env("TELEGRAM_BOT_TOKEN"),
            username=os.getenv("TELEGRAM_BOT_USERNAME"),
            official_username=os.getenv("TELEGRAM_PROD_BOT_USERNAME", OFFICIAL_BOT_USERNAME),
            mode=os.getenv("BOT_MODE", "polling").lower(),
            parse_mode=os.getenv("TELEGRAM_PARSE_MODE", "HTML"),
            rate_limit_per_second=_get_float_env("TELEGRAM_RATE_LIMIT_PER_SECOND", default=1.0),
            digest_poll_interval_seconds=_get_float_env("TELEGRAM_DIGEST_POLL_INTERVAL_SECONDS", default=60.0),
            admin_ids=_get_admin_ids_env("TELEGRAM_ADMIN_IDS"),
        )

        api_settings = SkillraApiSettings(
            base_url=_require_env("SKILLRA_API_BASE_URL"),
            token=_require_env("SKILLRA_API_TOKEN"),
            admin_token=_require_env("SKILLRA_ADMIN_TOKEN"),
            connect_timeout=_get_float_env("SKILLRA_API_CONNECT_TIMEOUT", 5.0),
            read_timeout=_get_float_env("SKILLRA_API_READ_TIMEOUT", 15.0),
            max_retries=_get_int_env("SKILLRA_API_MAX_RETRIES", 2),
            retry_backoff_seconds=_get_float_env("SKILLRA_API_RETRY_BACKOFF_SECONDS", 0.5),
        )
        runtime_env = _runtime_env()
        _validate_official_bot_api_target(bot_settings, api_settings, runtime_env)

        redis_settings = RedisSettings(url=_require_env("REDIS_URL"))

        digest_settings = DigestSettings(
            default_weekday=_get_int_env("TELEGRAM_DIGEST_WEEKDAY", 0),
            default_time_local=os.getenv("TELEGRAM_DIGEST_TIME_LOCAL", "10:00"),
            default_timezone=os.getenv("TELEGRAM_DIGEST_TIMEZONE", "Europe/Moscow"),
        )

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        log_format = _get_log_format(os.getenv("LOG_FORMAT", "kv"))

        webhook_settings = None
        if bot_settings.mode == "webhook":
            webhook_settings = WebhookSettings(
                url=_require_env("TELEGRAM_WEBHOOK_URL"),
                secret_token=_require_env("TELEGRAM_WEBHOOK_SECRET_TOKEN"),
                host=os.getenv("TELEGRAM_WEBHOOK_HOST", "0.0.0.0"),
                port=_get_int_env("TELEGRAM_WEBHOOK_PORT", 8080),
                path=os.getenv("TELEGRAM_WEBHOOK_PATH"),
                drop_pending_updates=_get_bool_env("TELEGRAM_DROP_PENDING_UPDATES", False),
                delete_webhook_on_shutdown=_get_bool_env("TELEGRAM_DELETE_WEBHOOK_ON_SHUTDOWN", False),
            )

        return cls(
            bot=bot_settings,
            api=api_settings,
            redis=redis_settings,
            digest=digest_settings,
            webhook=webhook_settings,
            log_level=log_level,
            log_format=log_format,
            runtime_env=runtime_env,
        )


@dataclass
class DigestSettings:
    default_weekday: int = 0
    default_time_local: str = "10:00"
    default_timezone: str = "Europe/Moscow"

    def __post_init__(self) -> None:
        if self.default_weekday < 0 or self.default_weekday > 6:
            raise SettingsError("TELEGRAM_DIGEST_WEEKDAY must be between 0 (Mon) and 6 (Sun)")
        if not _is_time_string(self.default_time_local):
            raise SettingsError("TELEGRAM_DIGEST_TIME_LOCAL must be in HH:MM format")
        if not self.default_timezone:
            raise SettingsError("TELEGRAM_DIGEST_TIMEZONE is required")


@dataclass
class WebhookSettings:
    url: str
    secret_token: str
    host: str = "0.0.0.0"
    port: int = 8080
    path: str | None = None
    drop_pending_updates: bool = False
    delete_webhook_on_shutdown: bool = False

    def __post_init__(self) -> None:
        if not self.url:
            raise SettingsError("TELEGRAM_WEBHOOK_URL is required in webhook mode")
        if not self.secret_token:
            raise SettingsError("TELEGRAM_WEBHOOK_SECRET_TOKEN is required in webhook mode")
        if not self.host:
            raise SettingsError("TELEGRAM_WEBHOOK_HOST must not be empty")
        if self.port <= 0:
            raise SettingsError("TELEGRAM_WEBHOOK_PORT must be positive")

        parsed_url = urlsplit(self.url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise SettingsError("TELEGRAM_WEBHOOK_URL must be an absolute URL")

        resolved_path = self.path or parsed_url.path or "/webhook"
        if not resolved_path.startswith("/"):
            raise SettingsError("TELEGRAM_WEBHOOK_PATH must start with '/'")
        self.path = resolved_path


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        raise SettingsError(f"{key} is required")
    return value


def _normalize_bot_username(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().removeprefix("@").lower()
    return normalized or None


def _is_local_api_base_url(base_url: str) -> bool:
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    return host in LOCAL_API_HOSTS


def _runtime_env() -> str:
    return (os.getenv("SKILLRA_RUNTIME_ENV") or os.getenv("SKILLRA_ENV") or "local").strip().lower()


def _validate_official_bot_api_target(bot: BotSettings, api: SkillraApiSettings, runtime_env: str) -> None:
    if bot.username != bot.official_username:
        return
    if runtime_env not in {"prod", "production"}:
        raise SettingsError(
            f"@{bot.official_username} is the production bot and cannot run with SKILLRA_RUNTIME_ENV={runtime_env}. "
            "Use a separate dev bot locally."
        )
    if not _is_local_api_base_url(api.base_url):
        return
    raise SettingsError(
        f"@{bot.official_username} must not use local SKILLRA_API_BASE_URL. "
        "Point the official bot to the production API/runtime."
    )


def _get_int_env(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SettingsError(f"{key} must be an integer") from exc


def _get_float_env(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise SettingsError(f"{key} must be a number") from exc


def _get_admin_ids_env(key: str) -> list[int]:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return []

    admin_ids: list[int] = []
    for raw_id in value.split(","):
        stripped = raw_id.strip()
        if not stripped:
            continue
        try:
            admin_ids.append(int(stripped))
        except ValueError as exc:
            raise SettingsError(f"{key} must be a comma-separated list of integers") from exc

    return admin_ids


def _get_bool_env(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise SettingsError(f"{key} must be a boolean (true/false)")


def _is_time_string(value: str) -> bool:
    return bool(re.fullmatch(r"[0-2]\d:[0-5]\d", value))


def _get_log_format(value: str) -> str:
    normalized = value.lower()
    if normalized not in {"json", "kv"}:
        raise SettingsError("LOG_FORMAT must be either 'json' or 'kv'")
    return normalized
