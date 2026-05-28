"""Handler for PDF report export."""

from __future__ import annotations

import logging
import os
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from telegram_bot import texts
from telegram_bot.handlers.analytics import build_persona_payload
from telegram_bot.logging_utils import mask_user_id
from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.errors import SkillraApiError

logger = logging.getLogger(__name__)
router = Router()


async def _load_persona_payload(
    message: Message,
    api_client: SkillraApiClient,
) -> tuple[int, dict[str, Any]] | None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return None

    try:
        profile = await api_client.get_profile(telegram_user_id)
    except SkillraApiError as exc:
        if exc.status_code == 404:
            await message.answer("Сначала настройте профиль через /start или /profile.")
            return None
        logger.exception("Failed to load profile for report", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer("Не удалось получить профиль. Попробуйте позже.")
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected profile loading error", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer("Не удалось получить профиль. Попробуйте позже.")
        return None

    if not profile:
        await message.answer("Сначала настройте профиль через /start или /profile.")
        return None

    return (
        telegram_user_id,
        build_persona_payload(
            profile,
            username=message.from_user.username if message.from_user else None,
        ),
    )


@router.message(Command("pdf"))
async def handle_pdf_report(message: Message, api_client: SkillraApiClient) -> None:
    """Export the current profile as a Skillra PDF report."""

    payload_result = await _load_persona_payload(message, api_client)
    if payload_result is None:
        return
    telegram_user_id, persona_payload = payload_result

    await message.answer("Генерирую PDF-отчёт по вашему профилю...")

    try:
        pdf_bytes = await api_client.export_persona_pdf(persona_payload)
    except Exception:  # noqa: BLE001
        logger.exception("PDF report generation failed", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer("Не удалось сгенерировать PDF. Попробуйте позже.")
        return

    if not pdf_bytes:
        await message.answer("Не удалось сгенерировать PDF. Попробуйте позже.")
        return

    await message.answer_document(
        BufferedInputFile(pdf_bytes, filename=f"skillra_report_{telegram_user_id}.pdf"),
        caption="Ваш персональный отчёт Skillra",
    )


@router.message(Command("csv"))
async def handle_csv_report(message: Message, api_client: SkillraApiClient) -> None:
    """Export the current profile skill-gap analysis as CSV."""

    payload_result = await _load_persona_payload(message, api_client)
    if payload_result is None:
        return
    telegram_user_id, persona_payload = payload_result

    await message.answer("Генерирую CSV по skill-gap...")

    try:
        csv_bytes = await api_client.export_persona_csv(persona_payload)
    except Exception:  # noqa: BLE001
        logger.exception("CSV report generation failed", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer("Не удалось сгенерировать CSV. Попробуйте позже.")
        return

    if not csv_bytes:
        await message.answer("Не удалось сгенерировать CSV. Попробуйте позже.")
        return

    await message.answer_document(
        BufferedInputFile(csv_bytes, filename=f"skill_gap_{telegram_user_id}.csv"),
        caption="CSV skill-gap",
    )


@router.message(Command("share"))
async def handle_share_report(message: Message, api_client: SkillraApiClient) -> None:
    """Create a public share link for the current profile skill-gap analysis."""

    payload_result = await _load_persona_payload(message, api_client)
    if payload_result is None:
        return
    telegram_user_id, persona_payload = payload_result

    try:
        share = await api_client.create_persona_share(persona_payload)
    except Exception:  # noqa: BLE001
        logger.exception("Share link creation failed", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer("Не удалось создать ссылку. Попробуйте позже.")
        return

    token = str(share.get("token") or "").strip()
    if not token:
        await message.answer("Не удалось создать ссылку. Попробуйте позже.")
        return

    public_base_url = os.getenv("SKILLRA_PUBLIC_BASE_URL", "https://skillra.ru").rstrip("/")
    await message.answer(f"Ссылка на skill-gap: {public_base_url}/share/{token}")
