"""Skillra Telegram bot package."""


def _relax_pydantic_protected_namespaces_for_aiogram() -> None:
    """Allow aiogram Telegram fields that intentionally start with model_."""

    try:
        from pydantic._internal import _config
    except Exception:  # pragma: no cover - best-effort compatibility shim
        return
    _config.config_defaults["protected_namespaces"] = ()


_relax_pydantic_protected_namespaces_for_aiogram()

from telegram_bot.main import main, run

__all__ = ["main", "run"]
