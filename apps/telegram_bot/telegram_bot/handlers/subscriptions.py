from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telegram_bot import texts
from telegram_bot.config import DigestSettings
from telegram_bot.services.api_client import SkillraApiClient, track_product_event_safely
from telegram_bot.services.errors import SkillraApiError, user_message_from_error

router = Router()

logger = logging.getLogger(__name__)

WEEKDAY_LABELS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

TIME_CHOICES = ["09:00", "12:00", "18:00"]

TIMEZONE_CHOICES = [
    "Europe/Moscow",
    "Europe/Kaliningrad",
    "Asia/Yekaterinburg",
    "Asia/Novosibirsk",
    "Asia/Vladivostok",
]

WEEKDAY_PREFIX = "sub:weekday:"
TIME_PREFIX = "sub:time:"
TIMEZONE_PREFIX = "sub:timezone:"


class SubscriptionSetup(StatesGroup):
    timezone = State()
    weekday = State()
    time_local = State()


@router.message(Command("subscribe"))
async def start_subscription(
    message: Message, state: FSMContext, data: dict[str, Any], api_client: SkillraApiClient | None = None
) -> None:
    digest_settings: DigestSettings = data.get("digest_settings")
    telegram_user_id = message.from_user.id if message.from_user else None
    track_product_event_safely(api_client, telegram_user_id, "digest_action_clicked", entity_type="subscription_flow")
    await _begin_subscription_flow(message, state, digest_settings)


@router.message(Command("unsubscribe"))
async def cancel_subscription(message: Message, api_client: SkillraApiClient, state: FSMContext) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    try:
        await api_client.delete_weekly_subscription(telegram_user_id)
    except SkillraApiError as exc:  # noqa: PERF203
        if exc.status_code == 404:
            await message.answer(texts.subscription_not_found_message())
            return
        logger.exception("Failed to delete subscription")
        await message.answer(user_message_from_error(exc, "Не удалось отменить подписку. Попробуйте позже."))
        return

    await state.clear()
    await message.answer(texts.subscription_disabled_message())


@router.message(Command("pause_digest"))
async def pause_subscription(message: Message, api_client: SkillraApiClient) -> None:
    """Sprint-007 TASK-02: Pause weekly digest subscription."""
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return
    try:
        sub = await api_client.get_weekly_subscription(telegram_user_id)
        payload = {
            "active": False,
            "weekday": sub["weekday"],
            "time_local": sub["time_local"],
            "timezone": sub["timezone"],
        }
        await api_client.upsert_weekly_subscription(telegram_user_id, payload)
        await message.answer("⏸ Подписка поставлена на паузу. Используй /resume_digest для возобновления.")
    except SkillraApiError as exc:
        await message.answer(user_message_from_error(exc, "Не удалось приостановить подписку."))


@router.message(Command("resume_digest"))
async def resume_subscription(message: Message, api_client: SkillraApiClient) -> None:
    """Sprint-007 TASK-02: Resume weekly digest subscription."""
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return
    try:
        sub = await api_client.get_weekly_subscription(telegram_user_id)
        payload = {
            "active": True,
            "weekday": sub["weekday"],
            "time_local": sub["time_local"],
            "timezone": sub["timezone"],
        }
        await api_client.upsert_weekly_subscription(telegram_user_id, payload)
        await message.answer("▶️ Подписка возобновлена! Следующий дайджест придёт по расписанию.")
    except SkillraApiError as exc:
        await message.answer(user_message_from_error(exc, "Не удалось возобновить подписку."))


@router.message(Command("subscription"))
@router.message(F.text.casefold() == "подписка")
async def show_subscription(message: Message, api_client: SkillraApiClient) -> None:
    """Sprint-007 TASK-03: View current subscription with next send date."""
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return
    try:
        sub = await api_client.get_weekly_subscription(telegram_user_id)
        status = "✅ Активна" if sub.get("active") else "⏸ На паузе"
        weekday_label = _weekday_label(sub.get("weekday"))
        time_local = escape(sub.get("time_local") or "—")
        timezone_name = str(sub.get("timezone") or "UTC")
        timezone = escape(timezone_name)
        next_send = compute_next_send_datetime(
            int(sub.get("weekday", 0)),
            str(sub.get("time_local") or "09:00"),
            timezone_name,
            _parse_optional_datetime(sub.get("last_sent_at")),
        )
        next_send_local = escape(next_send.astimezone(ZoneInfo(timezone_name)).strftime("%d.%m.%Y %H:%M"))
        text = (
            f"🔔 <b>Подписка</b>\n"
            f"Статус: {status}\n"
            f"День: <b>{weekday_label}</b>\n"
            f"Время: <b>{time_local}</b> ({timezone})\n"
            f"Следующий дайджест: <b>{next_send_local}</b>\n\n"
            f"Используй /pause_digest и /resume_digest для управления."
        )
        await message.answer(text, parse_mode="HTML")
    except SkillraApiError as exc:
        if exc.status_code == 404:
            await message.answer("У тебя нет активной подписки. Используй /subscribe для настройки.")
        else:
            await message.answer(user_message_from_error(exc, "Не удалось получить данные подписки."))


@router.callback_query(SubscriptionSetup.weekday, F.data.startswith(WEEKDAY_PREFIX))
async def choose_weekday(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.data or not callback.message:
        return

    weekday = int(callback.data.removeprefix(WEEKDAY_PREFIX))
    await state.update_data(weekday=weekday)
    await state.set_state(SubscriptionSetup.time_local)

    data = await state.get_data()
    default_time = str(data.get("time_local", "10:00"))
    timezone = str(data.get("timezone", "—"))
    await callback.message.answer(
        texts.subscription_time_prompt(default_time, timezone),
        reply_markup=_time_keyboard(_collect_time_options(default_time)),
    )


@router.callback_query(SubscriptionSetup.time_local, F.data.startswith(TIME_PREFIX))
async def choose_time(
    callback: CallbackQuery,
    state: FSMContext,
    api_client: SkillraApiClient,
    data: dict[str, Any],
) -> None:
    await callback.answer()
    if not callback.data or not callback.message or not callback.from_user:
        return

    time_local = callback.data.removeprefix(TIME_PREFIX)
    await state.update_data(time_local=time_local)

    digest_settings: DigestSettings = data.get("digest_settings")
    await _save_subscription(callback.message, callback.from_user.id, state, api_client, digest_settings)


@router.message(SubscriptionSetup.time_local, F.text)
async def enter_time(
    message: Message,
    state: FSMContext,
    api_client: SkillraApiClient,
    data: dict[str, Any],
) -> None:
    if not message.from_user:
        await message.answer(texts.cannot_determine_user())
        return

    time_local = (message.text or "").strip()
    if not _is_valid_time(time_local):
        await message.answer("Введите время в формате HH:MM, например 09:30.")
        return

    await state.update_data(time_local=time_local)

    digest_settings: DigestSettings = data.get("digest_settings")
    await _save_subscription(message, message.from_user.id, state, api_client, digest_settings)


def format_subscription_summary(subscription: dict[str, Any]) -> str:
    weekday_label = _weekday_label(subscription.get("weekday"))
    time_local = escape(subscription.get("time_local") or "—")
    timezone = escape(subscription.get("timezone") or "—")

    lines = ["<b>Подписка оформлена</b>"]
    status = "✅ Активна" if subscription.get("active", True) else "⏸ На паузе"
    lines.append(f"Статус: {status}")
    lines.append(f"День: <b>{weekday_label}</b>")
    lines.append(f"Время: <b>{time_local}</b> ({timezone})")

    try:
        next_send = compute_next_send_datetime(
            int(subscription.get("weekday", 0)),
            str(subscription.get("time_local") or "09:00"),
            str(subscription.get("timezone") or "UTC"),
            _parse_optional_datetime(subscription.get("last_sent_at")),
        )
        local_next = next_send.astimezone(ZoneInfo(str(subscription.get("timezone") or "UTC")))
        lines.append(f"Следующий дайджест: <b>{escape(local_next.strftime('%d.%m.%Y %H:%M'))}</b>")
    except (ValueError, ZoneInfoNotFoundError):
        lines.append("Следующий дайджест придёт по расписанию.")

    return "\n".join(lines)


def compute_next_send_datetime(
    weekday: int,
    time_local: str,
    timezone_name: str,
    last_sent_at: datetime | None,
    *,
    now: datetime | None = None,
) -> datetime:
    """Compute the next digest send datetime in UTC."""
    if not 0 <= weekday <= 6:
        raise ValueError("weekday must be in range 0..6")

    parsed_time = _parse_time_parts(time_local)
    if parsed_time is None:
        raise ValueError("time_local must be HH:MM")

    tzinfo = ZoneInfo(timezone_name)
    now_local = (now or datetime.now(timezone.utc)).astimezone(tzinfo)
    hours, minutes = parsed_time

    days_ahead = (weekday - now_local.weekday()) % 7
    candidate = (now_local + timedelta(days=days_ahead)).replace(
        hour=hours,
        minute=minutes,
        second=0,
        microsecond=0,
    )
    if candidate <= now_local:
        candidate += timedelta(days=7)

    if last_sent_at is not None:
        last_sent_local = _ensure_aware_utc(last_sent_at).astimezone(tzinfo)
        while candidate <= last_sent_local:
            candidate += timedelta(days=7)

    return candidate.astimezone(timezone.utc)


async def _begin_subscription_flow(message: Message, state: FSMContext, digest_settings: DigestSettings | None) -> None:
    settings = digest_settings or DigestSettings()
    await state.clear()
    await state.set_state(SubscriptionSetup.timezone)
    await state.update_data(time_local=settings.default_time_local, timezone=settings.default_timezone)

    await message.answer(
        texts.subscription_timezone_prompt(settings.default_timezone),
        reply_markup=_timezone_keyboard(_collect_timezone_options(settings.default_timezone)),
    )


@router.callback_query(SubscriptionSetup.timezone, F.data.startswith(TIMEZONE_PREFIX))
async def choose_timezone(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.data or not callback.message:
        return

    timezone = callback.data.removeprefix(TIMEZONE_PREFIX)
    await state.update_data(timezone=timezone)
    await state.set_state(SubscriptionSetup.weekday)

    await callback.message.answer(
        texts.subscription_weekday_prompt(),
        reply_markup=_weekday_keyboard(),
    )


@router.message(SubscriptionSetup.timezone, F.text)
async def enter_timezone(message: Message, state: FSMContext) -> None:
    timezone_input = (message.text or "").strip()
    if not timezone_input:
        await message.answer("Укажите таймзону в формате Region/City, например Europe/Moscow.")
        return

    if not _is_valid_timezone(timezone_input):
        await message.answer("Не нашёл такую таймзону. Проверьте написание, например Europe/Moscow.")
        return

    await state.update_data(timezone=timezone_input)
    await state.set_state(SubscriptionSetup.weekday)

    await message.answer(
        texts.subscription_weekday_prompt(),
        reply_markup=_weekday_keyboard(),
    )


async def _save_subscription(
    message: Message,
    telegram_user_id: int,
    state: FSMContext,
    api_client: SkillraApiClient,
    digest_settings: DigestSettings | None,
) -> None:
    state_data = await state.get_data()
    settings = digest_settings or DigestSettings()

    payload = {
        "active": True,
        "weekday": int(state_data.get("weekday", settings.default_weekday)),
        "time_local": str(state_data.get("time_local", settings.default_time_local)),
        "timezone": str(state_data.get("timezone", settings.default_timezone)),
    }

    try:
        subscription = await api_client.upsert_weekly_subscription(telegram_user_id, payload)
    except SkillraApiError as exc:
        logger.exception("Failed to save subscription")
        await message.answer(
            user_message_from_error(
                exc,
                "Не удалось сохранить настройки подписки. Попробуйте позже.",
            )
        )
        return

    await state.clear()
    await message.answer(format_subscription_summary(subscription))


def _weekday_keyboard():
    builder = InlineKeyboardBuilder()
    for idx, label in enumerate(WEEKDAY_LABELS):
        builder.button(text=label, callback_data=f"{WEEKDAY_PREFIX}{idx}")
    builder.adjust(2)
    return builder.as_markup()


def _timezone_keyboard(options: Iterable[str]):
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=option, callback_data=f"{TIMEZONE_PREFIX}{option}")
    builder.adjust(1)
    return builder.as_markup()


def _time_keyboard(options: Iterable[str]):
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=option, callback_data=f"{TIME_PREFIX}{option}")
    builder.adjust(3)
    return builder.as_markup()


def _collect_time_options(default_time: str) -> list[str]:
    options = list(TIME_CHOICES)
    if default_time not in options:
        options.insert(0, default_time)
    return options


def _collect_timezone_options(default_timezone: str) -> list[str]:
    options = list(TIMEZONE_CHOICES)
    if default_timezone not in options:
        options.insert(0, default_timezone)
    return options


def _weekday_label(value: Any) -> str:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return "—"

    if 0 <= index < len(WEEKDAY_LABELS):
        return WEEKDAY_LABELS[index]
    return "—"


def _is_valid_time(value: str) -> bool:
    return _parse_time_parts(value) is not None


def _parse_time_parts(value: str) -> tuple[int, int] | None:
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        return None

    try:
        hours = int(value[:2])
        minutes = int(value[3:])
    except ValueError:
        return None

    if 0 <= hours <= 23 and 0 <= minutes <= 59:
        return hours, minutes
    return None


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_valid_timezone(value: str) -> bool:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        return False
    return True
