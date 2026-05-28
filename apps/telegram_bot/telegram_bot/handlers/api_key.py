from __future__ import annotations

import logging
from datetime import datetime
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telegram_bot import texts
from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.errors import SkillraApiError, user_message_from_error

router = Router()
logger = logging.getLogger(__name__)

API_KEY_CREATE_CALLBACK = "api_key:create"
API_KEY_REVOKE_CALLBACK = "api_key:revoke"


@router.message(Command("api_key"))
async def show_or_create_api_key(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    try:
        status = await api_client.get_user_api_key_status(telegram_user_id)
    except SkillraApiError as exc:
        if exc.status_code == 404:
            await _create_and_send_key(message, api_client, telegram_user_id)
            return
        logger.exception("Failed to fetch user API key status")
        await message.answer(user_message_from_error(exc, "Не удалось получить статус ключа. Попробуйте позже."))
        return

    await message.answer(format_api_key_status(status), reply_markup=api_key_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == API_KEY_CREATE_CALLBACK)
async def rotate_api_key(callback: CallbackQuery, api_client: SkillraApiClient) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    await _create_and_send_key(callback.message, api_client, callback.from_user.id)


@router.callback_query(F.data == API_KEY_REVOKE_CALLBACK)
async def revoke_api_key(callback: CallbackQuery, api_client: SkillraApiClient) -> None:
    await callback.answer()
    if callback.from_user is None or callback.message is None:
        return

    try:
        result = await api_client.revoke_user_api_key(callback.from_user.id)
    except SkillraApiError as exc:
        if exc.status_code == 404:
            await callback.message.answer("Активный API-ключ не найден.")
            return
        logger.exception("Failed to revoke user API key")
        await callback.message.answer(user_message_from_error(exc, "Не удалось отозвать ключ. Попробуйте позже."))
        return

    revoked_at = _format_datetime(result.get("revoked_at"))
    await callback.message.answer(f"API-ключ отозван{f' {revoked_at}' if revoked_at else ''}.")


async def _create_and_send_key(message: Message, api_client: SkillraApiClient, telegram_user_id: int) -> None:
    try:
        payload = await api_client.create_user_api_key(telegram_user_id)
    except SkillraApiError as exc:
        logger.exception("Failed to create user API key")
        await message.answer(user_message_from_error(exc, "Не удалось выпустить ключ. Попробуйте позже."))
        return

    await message.answer(format_new_api_key(payload), reply_markup=api_key_keyboard(), parse_mode="HTML")


def api_key_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать новый", callback_data=API_KEY_CREATE_CALLBACK)
    builder.button(text="Отозвать", callback_data=API_KEY_REVOKE_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


def format_new_api_key(payload: dict[str, Any]) -> str:
    key = escape(str(payload.get("key") or ""))
    key_prefix = escape(str(payload.get("key_prefix") or ""))
    created_at = _format_datetime(payload.get("created_at"))
    lines = [
        "<b>API-ключ для Skillra Web</b>",
        "Скопируйте ключ сейчас: повторно показать его нельзя.",
        f"<code>{key}</code>",
    ]
    if key_prefix:
        lines.append(f"Префикс: <code>{key_prefix}</code>")
    if created_at:
        lines.append(f"Создан: {created_at}")
    return "\n".join(lines)


def format_api_key_status(status: dict[str, Any]) -> str:
    key_prefix = escape(str(status.get("key_prefix") or ""))
    created_at = _format_datetime(status.get("created_at"))
    last_used_at = _format_datetime(status.get("last_used_at"))
    active = "активен" if status.get("is_active", True) else "неактивен"

    lines = ["<b>API-ключ для Skillra Web</b>", f"Статус: {active}"]
    if key_prefix:
        lines.append(f"Префикс: <code>{key_prefix}</code>")
    if created_at:
        lines.append(f"Создан: {created_at}")
    if last_used_at:
        lines.append(f"Последнее использование: {last_used_at}")
    lines.append("Чтобы получить новый ключ, старый будет отозван автоматически.")
    return "\n".join(lines)


def _format_datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return escape(str(value))
