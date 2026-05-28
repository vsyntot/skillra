"""Admin-only command handlers for the Telegram bot."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from telegram_bot import texts
from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.errors import SkillraApiError, user_message_from_error

router = Router()
logger = logging.getLogger(__name__)
ACCESS_DENIED_MESSAGE = texts.access_denied_message()


def _is_admin(user_id: int | None, admin_ids: set[int]) -> bool:
    return user_id is not None and user_id in admin_ids


async def _ensure_admin(message: Message, admin_ids: set[int]) -> bool:
    telegram_user_id = message.from_user.id if message.from_user else None
    if _is_admin(telegram_user_id, admin_ids):
        return True

    await message.answer(ACCESS_DENIED_MESSAGE)
    return False


def _extract_datastore(data_health: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data_health:
        return None

    datastore = data_health.get("datastore")
    if isinstance(datastore, dict):
        return datastore

    details = data_health.get("details")
    if isinstance(details, dict):
        datastore_details = details.get("datastore")
        if isinstance(datastore_details, dict):
            return datastore_details

    return None


def format_admin_health(data_health: dict[str, Any] | None) -> str:
    lines = ["<b>Admin health (/v1/health)</b>"]
    datastore = _extract_datastore(data_health)
    if not datastore:
        lines.append("Данные: неизвестно")
        return "\n".join(lines)

    ready = datastore.get("ready")
    if ready is True:
        lines.append("Данные: ✅ готовы")
    elif ready is False:
        lines.append("Данные: ❌ не готовы")
    else:
        lines.append("Данные: состояние неизвестно")

    dataset_meta = datastore.get("dataset_meta")
    generated_at = None
    if isinstance(dataset_meta, dict):
        generated_at = dataset_meta.get("generated_at_utc") or dataset_meta.get("generated_at")

    if generated_at:
        lines.append(f"Сгенерировано: {generated_at}")

    return "\n".join(lines)


def format_reload_response(payload: dict[str, Any]) -> str:
    status = payload.get("status") or "unknown"
    datastore = _extract_datastore(payload) or {}
    ready = datastore.get("ready")
    ready_text = "неизвестно"
    if ready is True:
        ready_text = "готовы"
    elif ready is False:
        ready_text = "не готовы"

    return f"Reload статус: {status}\nДанные: {ready_text}"


@router.message(Command("admin_health"))
async def handle_admin_health(message: Message, api_client: SkillraApiClient, admin_ids: set[int]) -> None:
    if not await _ensure_admin(message, admin_ids):
        return

    try:
        data_health = await api_client.data_health()
    except httpx.HTTPError:
        logger.exception("Failed to fetch admin health")
        await message.answer("Не удалось получить /v1/health")
        return
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error while fetching admin health")
        await message.answer("Не удалось получить /v1/health")
        return

    await message.answer(format_admin_health(data_health))


@router.message(Command(commands=["reload_data", "admin_reload_data"]))
async def handle_admin_reload_data(message: Message, api_client: SkillraApiClient, admin_ids: set[int]) -> None:
    if not await _ensure_admin(message, admin_ids):
        return

    try:
        payload = await api_client.reload_data()
    except SkillraApiError as exc:
        logger.warning(
            "Reload data failed",
            extra={"status": exc.status_code, "error_code": exc.error_code},
        )
        await message.answer(user_message_from_error(exc, "Не удалось перезагрузить данные"))
        return
    except httpx.HTTPError:
        logger.exception("Failed to call reload-data")
        await message.answer("Не удалось перезагрузить данные")
        return
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error while calling reload-data")
        await message.answer("Не удалось перезагрузить данные")
        return

    await message.answer(format_reload_response(payload))


@router.message(Command("broadcast_update"))
async def handle_broadcast_update(message: Message, api_client: SkillraApiClient, admin_ids: set[int]) -> None:
    """Reload data and notify the admin chat with resulting metadata."""
    if not await _ensure_admin(message, admin_ids):
        return

    try:
        payload = await api_client.reload_data()
    except SkillraApiError as exc:
        logger.warning(
            "Broadcast update reload failed",
            extra={"status": exc.status_code, "error_code": exc.error_code},
        )
        await message.answer(user_message_from_error(exc, "Не удалось обновить данные для рассылки"))
        return
    except httpx.HTTPError:
        logger.exception("Failed to call reload-data for broadcast update")
        await message.answer("Не удалось обновить данные для рассылки")
        return

    await message.answer("📊 Данные рынка обновлены.\n" + format_reload_response(payload))


@router.message(Command("admin_due"))
async def handle_admin_due(message: Message, api_client: SkillraApiClient, admin_ids: set[int]) -> None:
    if not await _ensure_admin(message, admin_ids):
        return

    try:
        due_subscriptions = await api_client.get_due_subscriptions()
    except httpx.HTTPError:
        logger.exception("Failed to fetch due subscriptions")
        await message.answer("Не удалось получить due подписки")
        return
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error while fetching due subscriptions")
        await message.answer("Не удалось получить due подписки")
        return

    await message.answer(f"Количество due подписок: {len(due_subscriptions)}")
