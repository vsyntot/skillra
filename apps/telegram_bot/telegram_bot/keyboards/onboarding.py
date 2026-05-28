"""Inline keyboards for onboarding selections."""

from __future__ import annotations

import math
from typing import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

SKIP_DOMAIN_VALUE = "__skip__"


class SelectionCallbackFactory:
    prefix_separator = ":"

    @classmethod
    def pack(cls, step: str, value: str) -> str:
        return f"{step}{cls.prefix_separator}{value}"

    @classmethod
    def unpack(cls, data: str) -> tuple[str, str] | None:
        if cls.prefix_separator not in data:
            return None
        step, value = data.split(cls.prefix_separator, maxsplit=1)
        return step, value


class PaginationCallbackFactory:
    prefix = "page"
    prefix_separator = ":"

    @classmethod
    def pack(cls, step: str, page: int) -> str:
        return f"{cls.prefix}{cls.prefix_separator}{step}{cls.prefix_separator}{page}"

    @classmethod
    def unpack(cls, data: str) -> tuple[str, int] | None:
        parts = data.split(cls.prefix_separator)
        if len(parts) != 3 or parts[0] != cls.prefix:
            return None
        try:
            page = int(parts[2])
        except ValueError:
            return None
        return parts[1], page


def _build_paginated_keyboard(
    values: Iterable[str],
    step: str,
    page: int,
    page_size: int,
    *,
    allow_skip: bool = False,
) -> InlineKeyboardMarkup:
    options = list(values)
    total_pages = max(1, math.ceil(len(options) / page_size) or 1)
    current_page = max(1, min(page, total_pages))
    start = (current_page - 1) * page_size
    end = start + page_size

    builder = InlineKeyboardBuilder()
    for option in options[start:end]:
        builder.button(text=option, callback_data=SelectionCallbackFactory.pack(step, option))
    if allow_skip:
        builder.button(
            text="Пропустить",
            callback_data=SelectionCallbackFactory.pack(step, SKIP_DOMAIN_VALUE),
        )
    builder.adjust(2)

    if total_pages > 1:
        navigation_buttons = []
        if current_page > 1:
            navigation_buttons.append(
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=PaginationCallbackFactory.pack(step, current_page - 1),
                )
            )
        navigation_buttons.append(
            InlineKeyboardButton(
                text=f"{current_page}/{total_pages}",
                callback_data=PaginationCallbackFactory.pack(step, current_page),
            )
        )
        if current_page < total_pages:
            navigation_buttons.append(
                InlineKeyboardButton(
                    text="Далее ▶️",
                    callback_data=PaginationCallbackFactory.pack(step, current_page + 1),
                )
            )
        builder.row(*navigation_buttons)

    return builder.as_markup()


def build_role_keyboard(values: Iterable[str], page: int, page_size: int) -> InlineKeyboardMarkup:
    return _build_paginated_keyboard(values, "role", page, page_size)


def build_grade_keyboard(values: Iterable[str], page: int, page_size: int) -> InlineKeyboardMarkup:
    return _build_paginated_keyboard(values, "grade", page, page_size)


def build_city_tier_keyboard(values: Iterable[str], page: int, page_size: int) -> InlineKeyboardMarkup:
    return _build_paginated_keyboard(values, "city_tier", page, page_size)


def build_work_mode_keyboard(values: Iterable[str], page: int, page_size: int) -> InlineKeyboardMarkup:
    return _build_paginated_keyboard(values, "work_mode", page, page_size)


def build_domain_keyboard(values: Iterable[str], page: int, page_size: int) -> InlineKeyboardMarkup:
    return _build_paginated_keyboard(values, "domain", page, page_size, allow_skip=True)


__all__ = [
    "SKIP_DOMAIN_VALUE",
    "SelectionCallbackFactory",
    "PaginationCallbackFactory",
    "build_role_keyboard",
    "build_grade_keyboard",
    "build_city_tier_keyboard",
    "build_work_mode_keyboard",
    "build_domain_keyboard",
]
