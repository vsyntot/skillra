"""Helpers for skill parsing and suggestions."""

from __future__ import annotations

import difflib
import logging
from html import escape
from typing import Iterable

from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.meta_cache import MetaCache

logger = logging.getLogger(__name__)

PREFIXES = ("skill_", "has_")


def normalize_skill_name(name: str) -> str:
    normalized = name.strip().lower()
    for prefix in PREFIXES:
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix)
    return normalized


def parse_skills(text: str) -> list[str]:
    parts = [normalize_skill_name(part) for part in text.split(",")]
    skills: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        skills.append(part)
    return skills


def suggest_skills(
    skills: Iterable[str],
    available_skills: Iterable[str],
    *,
    suggestions_limit: int = 5,
    cutoff: float = 0.4,
) -> dict[str, list[str]]:
    available_normalized: list[str] = []
    seen: set[str] = set()
    for skill in available_skills:
        normalized = normalize_skill_name(skill)
        if normalized in seen:
            continue
        seen.add(normalized)
        available_normalized.append(normalized)
    return {
        skill: difflib.get_close_matches(skill, available_normalized, n=suggestions_limit, cutoff=cutoff)
        for skill in skills
    }


def find_unknown_skills(
    skills: Iterable[str],
    available_skills: Iterable[str],
    *,
    suggestions_limit: int = 5,
) -> tuple[list[str], dict[str, list[str]]]:
    available_set = {normalize_skill_name(skill) for skill in available_skills}
    unknown: list[str] = []
    for skill in skills:
        if skill in available_set:
            continue
        unknown.append(skill)

    suggestions = suggest_skills(unknown, available_set, suggestions_limit=suggestions_limit)
    return unknown, suggestions


def format_unknown_skills_message(
    unknown: list[str],
    suggestions: dict[str, list[str]],
    *,
    intro: str,
    action_prompt: str,
) -> str:
    lines = [intro]
    for skill in unknown:
        hint = suggestions.get(skill) or []
        suggestion_text = f" Возможно вы имели в виду: {', '.join(hint)}" if hint else ""
        lines.append(f"• {escape(skill)}.{suggestion_text}")
    lines.append(action_prompt)
    return "\n".join(lines)


async def build_skill_suggestions(
    unknown: list[str],
    api_client: SkillraApiClient,
    meta_cache: MetaCache,
) -> dict[str, list[str]]:
    try:
        available_skills = await meta_cache.get_skills(api_client)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load skills meta for suggestions", exc_info=True)
        return {skill: [] for skill in unknown}

    return suggest_skills(unknown, available_skills)
