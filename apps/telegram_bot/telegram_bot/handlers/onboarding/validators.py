"""Input validation helpers for the onboarding and settings flows."""

from __future__ import annotations

import logging

from telegram_bot.keyboards.onboarding import SKIP_DOMAIN_VALUE
from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.meta_cache import MetaCache
from telegram_bot.services.skills import find_unknown_skills, format_unknown_skills_message

logger = logging.getLogger(__name__)

__all__ = [
    "match_user_value",
    "validate_skills",
    "load_available_skills",
    "is_settings_flow",
]


def match_user_value(value: str, options: list[str], *, allow_skip: bool = False) -> tuple[bool, str | None]:
    """Return (is_valid, matched_value) for a user-provided text against a list of options.

    If *allow_skip* is True and the user typed "skip" / "пропустить",
    returns (True, SKIP_DOMAIN_VALUE).
    """
    normalized = value.strip()
    if not normalized:
        return False, None
    if allow_skip and normalized.lower() in {"skip", "пропустить"}:
        return True, SKIP_DOMAIN_VALUE

    options_map = {option.lower(): option for option in options}
    matched = options_map.get(normalized.lower())
    if matched is None:
        return False, None
    return True, matched


async def load_available_skills(api_client: SkillraApiClient, meta_cache: MetaCache) -> list[str] | None:
    """Fetch available skill names from the meta cache; return None on failure."""
    try:
        return await meta_cache.get_skills(api_client)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to validate skills against meta", exc_info=True)
        return None


async def validate_skills(
    skills: list[str], api_client: SkillraApiClient, meta_cache: MetaCache
) -> tuple[bool, str | None]:
    """Validate *skills* against the meta catalogue.

    Returns (True, None) when all skills are recognised or the catalogue is
    unavailable (fail-open).  Returns (False, error_message) on unknown skills.
    """
    available_skills = await load_available_skills(api_client, meta_cache)
    if available_skills is None:
        return True, None
    unknown, suggestions = find_unknown_skills(skills, available_skills)
    if unknown:
        return False, format_unknown_skills_message(
            unknown,
            suggestions,
            intro="Мы не нашли такие навыки в справочнике:",
            action_prompt="Пожалуйста, введите навыки заново, используя канонические названия.",
        )
    return True, None


def is_settings_flow(data: dict) -> bool:
    """Return True when the FSM session data belongs to the settings (edit) flow."""
    return data.get("flow") == "settings"
