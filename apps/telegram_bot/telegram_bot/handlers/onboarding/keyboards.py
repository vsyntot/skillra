"""Keyboard builder functions for the onboarding and settings flows."""

from __future__ import annotations

from typing import Iterable

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telegram_bot.handlers.commands import build_menu_keyboard  # re-export for convenience
from telegram_bot.keyboards.onboarding import (
    SKIP_DOMAIN_VALUE,
    build_city_tier_keyboard,
    build_domain_keyboard,
    build_grade_keyboard,
    build_role_keyboard,
    build_work_mode_keyboard,
)

from .states import (
    CONFIRM_CALLBACK,
    EDIT_CALLBACK,
    ONBOARDING_PAGE_SIZE,
    PROFILE_EDIT_CALLBACK,
    RESUME_SKIP_CALLBACK,
    RESUME_UPLOAD_CALLBACK,
    SETTINGS_FIELD_PREFIX,
    SETTINGS_FIELDS,
    SETTINGS_VALUE_PREFIX,
    START_KEEP_PROFILE_CALLBACK,
    START_RESTART_CALLBACK,
    START_RESUME_CALLBACK,
    START_UPDATE_PROFILE_CALLBACK,
)

__all__ = [
    "build_menu_keyboard",
    "build_profile_actions_keyboard",
    "build_resume_keyboard",
    "build_resume_upload_keyboard",
    "build_profile_exists_keyboard",
    "build_step_keyboard",
    "settings_keyboard",
    "settings_options_keyboard",
    "skills_confirmation_keyboard",
    "SKIP_DOMAIN_VALUE",
]


def build_profile_actions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Редактировать", callback_data=PROFILE_EDIT_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


def build_resume_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Продолжить", callback_data=START_RESUME_CALLBACK)
    builder.button(text="Начать заново", callback_data=START_RESTART_CALLBACK)
    builder.adjust(2)
    return builder.as_markup()


def build_profile_exists_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Обновить профиль", callback_data=START_UPDATE_PROFILE_CALLBACK)
    builder.button(text="Оставить", callback_data=START_KEEP_PROFILE_CALLBACK)
    builder.adjust(2)
    return builder.as_markup()


def build_resume_upload_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Загрузить резюме", callback_data=RESUME_UPLOAD_CALLBACK)
    builder.button(text="Пропустить", callback_data=RESUME_SKIP_CALLBACK)
    builder.adjust(2)
    return builder.as_markup()


def settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, label in SETTINGS_FIELDS:
        builder.button(text=label, callback_data=f"{SETTINGS_FIELD_PREFIX}:{field}")
    builder.adjust(2)
    return builder.as_markup()


def settings_options_keyboard(options: Iterable[str], field: str, *, allow_skip: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(
            text=option,
            callback_data=f"{SETTINGS_VALUE_PREFIX}:{field}:{option}",
        )
    if allow_skip:
        builder.button(
            text="Пропустить",
            callback_data=f"{SETTINGS_VALUE_PREFIX}:{field}:{SKIP_DOMAIN_VALUE}",
        )
    builder.adjust(2)
    return builder.as_markup()


def skills_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Все верно", callback_data=CONFIRM_CALLBACK)
    builder.button(text="Изменить", callback_data=EDIT_CALLBACK)
    builder.adjust(2)
    return builder.as_markup()


def build_step_keyboard(options: list[str], step: str, *, page: int) -> InlineKeyboardMarkup:
    """Return the inline keyboard for a given onboarding step and page."""
    builders: dict[str, object] = {
        "role": build_role_keyboard,
        "grade": build_grade_keyboard,
        "city_tier": build_city_tier_keyboard,
        "work_mode": build_work_mode_keyboard,
        "domain": build_domain_keyboard,
    }
    builder_fn = builders.get(step)
    if builder_fn is None:
        return InlineKeyboardBuilder().as_markup()
    return builder_fn(options, page, ONBOARDING_PAGE_SIZE)  # type: ignore[operator]
