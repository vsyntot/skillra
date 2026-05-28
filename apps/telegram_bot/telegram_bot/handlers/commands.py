"""Command handlers for static bot commands."""

from __future__ import annotations

import logging
from html import escape
from typing import Any

import httpx
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telegram_bot import texts
from telegram_bot.logging_utils import mask_user_id
from telegram_bot.services.api_client import SkillraApiClient, track_product_event_safely
from telegram_bot.services.errors import SkillraApiError, user_message_from_error

router = Router()
logger = logging.getLogger(__name__)
DIGEST_PROFILE_FALLBACK = texts.digest_profile_fallback()

FIRST_SESSION_ROUTE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Профиль", "/profile", ("create_profile", "complete_profile")),
    ("Рынок", "/market", ("data_unavailable",)),
    ("План", "/plan", ("create_plan", "update_application_outcome", "continue_plan")),
    ("Skill-gap", "/plan_recommend", ("generate_plan_actions",)),
    ("Вакансии", "/search", ("find_vacancy",)),
    ("Дайджест", "/subscribe", ("enable_digest",)),
)

PLAN_LABELS = {
    "free": "Free",
    "trial": "Trial",
    "pro": "Pro",
    "admin": "Admin",
}
SUBSCRIPTION_STATE_LABELS = {
    "none": "нет платной подписки",
    "trialing": "пробный период",
    "active": "активен",
    "cancel_at_period_end": "отменится в конце периода",
    "expired": "истёк",
    "refunded": "возврат оформлен",
    "payment_failed": "платёж не прошёл",
    "provider_unavailable": "платёжный провайдер недоступен",
    "past_due": "платёж не прошёл",
    "cancelled": "отменён",
}
PREMIUM_FEATURE_LABELS = {
    "career_plan.generate_actions": "рекомендации из skill gap",
    "skill_gap.export": "экспорт skill gap",
    "trends.advanced": "расширенные тренды",
}


def format_welcome_message() -> str:
    return texts.welcome_message()


def format_help_message(is_admin: bool = False) -> str:
    return texts.help_message(is_admin)


def format_menu_message() -> str:
    return texts.menu_message()


def format_commercial_state_message(state: dict[str, Any]) -> list[str]:
    plan = PLAN_LABELS.get(str(state.get("plan") or "free"), str(state.get("plan") or "Free"))
    subscription_state = SUBSCRIPTION_STATE_LABELS.get(
        str(state.get("subscription_state") or "none"),
        str(state.get("subscription_state") or "—"),
    )
    lines = [f"💳 Тариф: <b>{escape(plan)}</b>", f"Статус тарифа: {escape(subscription_state)}"]
    trial_ends_at = state.get("trial_ends_at")
    current_period_ends_at = state.get("current_period_ends_at")
    if trial_ends_at:
        lines.append(f"Пробный период до: {escape(str(trial_ends_at)[:10])}")
    if current_period_ends_at:
        lines.append(f"Период оплаты до: {escape(str(current_period_ends_at)[:10])}")
    if str(state.get("subscription_state")) in {"payment_failed", "provider_unavailable", "past_due"}:
        lines.append(
            "Если оплата не прошла, открой web-аккаунт или напиши в поддержку. Данные провайдера в чат не отправляем."
        )
    locked = state.get("locked_features")
    if isinstance(locked, list) and locked:
        labels = [PREMIUM_FEATURE_LABELS.get(str(item), str(item)) for item in locked]
        lines.append("Закрыто: " + escape(", ".join(labels)))
        lines.append("Управление тарифом: https://skillra.ru/account")
        lines.append("Для входа в web используй /api_key.")
    else:
        lines.append("Pro-возможности доступны.")
    return lines


def format_next_best_action_message(action: dict[str, Any]) -> str:
    title = escape(str(action.get("title") or "Следующий шаг"))
    reason = escape(str(action.get("reason") or "Skillra подобрала ближайшее действие."))
    cta = escape(str(action.get("cta") or "Открыть"))
    command = action.get("command")
    route = action.get("route")
    trust_warning = action.get("trust_warning")
    profile_quality = action.get("profile_quality") if isinstance(action.get("profile_quality"), dict) else {}
    score = profile_quality.get("score")
    missing_fields = profile_quality.get("missing_fields")

    lines = [
        "<b>Личный следующий шаг</b>",
        f"<b>{title}</b>",
        reason,
    ]
    if score is not None:
        lines.append(f"Профиль: {escape(str(score))}%")
    if isinstance(missing_fields, list) and missing_fields:
        lines.append("Нужно дозаполнить: " + escape(", ".join(str(field) for field in missing_fields[:4])))
    if command:
        lines.append(f"Команда: <code>{escape(str(command))}</code>")
    if route:
        lines.append(f"Web-раздел: <code>{escape(str(route))}</code>")
    lines.append(f"Действие: <b>{cta}</b>")
    lines.append("")
    lines.append("<b>Первый сеанс</b>")
    lines.extend(_format_first_session_route(action.get("state")))
    if trust_warning:
        lines.append("")
        lines.append("Предупреждение по данным: " + escape(str(trust_warning)))
    return "\n".join(lines)


def _format_first_session_route(state: object) -> list[str]:
    current_state = str(state or "")
    lines: list[str] = []
    for index, (title, command, current_states) in enumerate(FIRST_SESSION_ROUTE, start=1):
        current_label = " <b>сейчас</b>" if current_state in current_states else ""
        lines.append(f"{index}. {escape(title)}:{current_label} <code>{escape(command)}</code>")
    return lines


def build_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Карта рынка"), KeyboardButton(text="Skill-gap")],
            [KeyboardButton(text="/plan"), KeyboardButton(text="/trends")],
            [KeyboardButton(text="/search"), KeyboardButton(text="/digest")],
            [KeyboardButton(text="Подписка"), KeyboardButton(text="/account")],
            [KeyboardButton(text="/profile"), KeyboardButton(text="/api_key")],
            [KeyboardButton(text="/settings")],
        ],
        resize_keyboard=True,
    )


def format_privacy_message() -> str:
    return texts.privacy_message()


def build_bot_commands(include_admin: bool = False) -> list[BotCommand]:
    commands = [BotCommand(command=name, description=description) for name, description in texts.USER_COMMANDS]
    if include_admin:
        commands.extend(BotCommand(command=name, description=description) for name, description in texts.ADMIN_COMMANDS)
    return commands


def format_status_message(
    service_health: dict[str, Any] | None,
    data_health: dict[str, Any] | None,
    data_health_error: str | None = None,
    due_subscriptions_count: int | None = None,
) -> str:
    return texts.format_status_message(
        service_health,
        data_health,
        data_health_error,
        due_subscriptions_count,
    )


ACTION_TYPE_LABELS = {
    "learning": "обучение",
    "application": "отклик",
    "portfolio": "портфолио",
    "networking": "нетворкинг",
    "saved_vacancy": "вакансия",
    "other": "другое",
}

ACTION_STATUS_LABELS = {
    "planned": "план",
    "in_progress": "в работе",
    "done": "готово",
    "skipped": "пропущено",
}

PLAN_STATUS_LABELS = {
    "active": "активен",
    "completed": "завершён",
    "archived": "архив",
}

PLAN_ACTION_CALLBACK_PREFIX = "plan:act:"
PLAN_ACTION_STATUS_OPTIONS = {
    "in_progress": "В работе",
    "done": "Готово",
    "skipped": "Отложить",
}


def _format_optional(value: object) -> str:
    return escape(str(value)) if value else "не указано"


def format_career_plan_message(plan: dict[str, Any]) -> str:
    actions_payload = plan.get("actions")
    actions = actions_payload if isinstance(actions_payload, list) else []
    completed = sum(1 for action in actions if isinstance(action, dict) and action.get("status") == "done")
    active = sum(
        1
        for action in actions
        if isinstance(action, dict) and str(action.get("status") or "") not in {"done", "skipped"}
    )
    raw_plan_status = str(plan.get("status") or "")
    plan_status = PLAN_STATUS_LABELS.get(raw_plan_status, raw_plan_status or "—")

    lines = [
        "<b>Карьерный план</b>",
        f"Статус: <b>{escape(plan_status)}</b>",
        (
            "Цель: "
            f"<b>{_format_optional(plan.get('target_role'))}</b>"
            f" / {_format_optional(plan.get('target_grade'))}"
        ),
        (
            "Контекст: "
            f"{_format_optional(plan.get('target_city_tier'))}"
            f" / {_format_optional(plan.get('target_work_mode'))}"
            f" / {_format_optional(plan.get('target_domain'))}"
        ),
        f"Прогресс: {completed}/{len(actions)} завершено, активных: {active}",
    ]

    notes = plan.get("notes")
    if notes:
        lines.append(f"Заметки: {escape(str(notes))}")

    if actions:
        lines.append("")
        lines.append("<b>Ближайшие действия</b>:")
        sorted_actions = sorted(
            [action for action in actions if isinstance(action, dict)],
            key=lambda action: (int(action.get("priority") or 100), int(action.get("id") or 0)),
        )
        for action in sorted_actions[:5]:
            title = escape(str(action.get("title") or "Без названия"))
            raw_action_type = str(action.get("action_type") or "")
            action_type = ACTION_TYPE_LABELS.get(raw_action_type, raw_action_type)
            status = ACTION_STATUS_LABELS.get(str(action.get("status") or ""), str(action.get("status") or ""))
            skill = action.get("skill_name")
            suffix = f" · {escape(str(skill))}" if skill else ""
            lines.append(f"• [{escape(status)}] {title} ({escape(action_type)}{suffix})")
        if len(sorted_actions) > 5:
            lines.append(f"Ещё действий: {len(sorted_actions) - 5}")
    else:
        lines.append("")
        lines.append("Действий пока нет. Добавьте их в web-приложении: /api_key.")

    return "\n".join(lines)


def build_plan_actions_keyboard(plan: dict[str, Any]):
    actions_payload = plan.get("actions")
    actions = actions_payload if isinstance(actions_payload, list) else []
    sorted_actions = sorted(
        [
            action
            for action in actions
            if isinstance(action, dict)
            and action.get("id") is not None
            and action.get("action_type") != "saved_vacancy"
            and str(action.get("status") or "") not in {"done", "skipped"}
        ],
        key=lambda action: (int(action.get("priority") or 100), int(action.get("id") or 0)),
    )
    if not sorted_actions:
        return None

    builder = InlineKeyboardBuilder()
    for index, action in enumerate(sorted_actions[:5], start=1):
        action_id = int(action["id"])
        for status, label in PLAN_ACTION_STATUS_OPTIONS.items():
            builder.button(
                text=f"{index} · {label}",
                callback_data=f"{PLAN_ACTION_CALLBACK_PREFIX}{action_id}:{status}",
            )
    builder.adjust(3)
    return builder.as_markup()


def _parse_plan_action_callback(data: str | None) -> tuple[int, str] | None:
    if not data or not data.startswith(PLAN_ACTION_CALLBACK_PREFIX):
        return None
    raw = data.removeprefix(PLAN_ACTION_CALLBACK_PREFIX)
    raw_action_id, separator, status = raw.partition(":")
    if not separator or status not in PLAN_ACTION_STATUS_OPTIONS:
        return None
    try:
        return int(raw_action_id), status
    except ValueError:
        return None


def _parse_mode_from_format(format_hint: str | None) -> ParseMode | None:
    if not format_hint:
        return None

    try:
        return ParseMode(format_hint)
    except ValueError:
        return None


async def _try_send_digest_chart(message: Message, api_client: SkillraApiClient, telegram_user_id: int) -> None:
    masked_user_id = mask_user_id(telegram_user_id)
    try:
        chart_bytes = await api_client.get_digest_chart(telegram_user_id)
    except SkillraApiError as exc:
        status = exc.status_code
        if status in {400, 404}:
            logger.warning(
                "Digest chart unavailable",
                extra={"user_id": masked_user_id, "status": status},
            )
            return
        if status >= 500:
            logger.exception(
                "Digest chart request failed",
                extra={"user_id": masked_user_id, "status": status},
            )
            return
        logger.exception(
            "Unexpected status while fetching digest chart",
            extra={"user_id": masked_user_id, "status": status},
        )
        return
    except Exception:  # noqa: BLE001
        logger.exception(
            "Unexpected error while fetching digest chart",
            extra={"user_id": masked_user_id},
        )
        return

    if not chart_bytes:
        logger.warning("Empty digest chart", extra={"user_id": masked_user_id})
        return

    try:
        await message.answer_photo(
            BufferedInputFile(chart_bytes, filename="digest.png"),
            caption="Digest график",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send digest chart", extra={"user_id": masked_user_id})


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    admin_ids: set[int] = message.bot.get("admin_ids", set())
    telegram_user_id = message.from_user.id if message.from_user else None
    is_admin = telegram_user_id in admin_ids

    await message.answer(format_help_message(is_admin))


@router.message(Command("menu"))
async def handle_menu(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(format_menu_message(), reply_markup=build_menu_keyboard())
        return
    track_product_event_safely(
        telegram_user_id=telegram_user_id, api_client=api_client, event_name="first_session_viewed"
    )

    try:
        next_action = await api_client.get_next_best_action(telegram_user_id, source="bot")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to fetch next best action", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer(format_menu_message(), reply_markup=build_menu_keyboard())
        return

    await message.answer(
        format_menu_message() + "\n\n" + format_next_best_action_message(next_action),
        parse_mode=ParseMode.HTML,
        reply_markup=build_menu_keyboard(),
    )


@router.message(Command("privacy"))
async def handle_privacy(message: Message) -> None:
    await message.answer(format_privacy_message())


@router.message(Command("digest"))
async def handle_digest(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer("Команда доступна только в личных чатах.")
        return

    try:
        preview = await api_client.get_digest_preview(telegram_user_id, source="bot")
    except SkillraApiError as exc:
        error_code = exc.error_code
        if not error_code and isinstance(exc.payload, dict):
            error_code = exc.payload.get("error_code")

        if exc.status_code == 404 or error_code == "PROFILE_NOT_FOUND":
            await message.answer(texts.digest_profile_fallback(), reply_markup=build_menu_keyboard())
            return

        logger.exception("Failed to fetch digest preview", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer(
            user_message_from_error(
                exc,
                "Не удалось загрузить дайджест. Попробуйте позже.",
            )
        )
        return
    except Exception:  # noqa: BLE001
        logger.exception(
            "Unexpected error while fetching digest preview",
            extra={"user_id": mask_user_id(telegram_user_id)},
        )
        await message.answer("Не удалось загрузить дайджест. Попробуйте позже.")
        return

    content = preview.get("text") or preview.get("content")
    if not content:
        await message.answer("Дайджест пока недоступен.")
        return

    parse_mode = _parse_mode_from_format(preview.get("format"))
    await message.answer(content, parse_mode=parse_mode)
    await _try_send_digest_chart(message, api_client, telegram_user_id)


def format_digest_history_message(history: dict[str, Any]) -> str:
    items_payload = history.get("items")
    items = items_payload if isinstance(items_payload, list) else []
    total = history.get("total", len(items))
    lines = ["<b>История дайджестов</b>", f"Всего записей: <b>{escape(str(total))}</b>"]

    if not items:
        lines.append("Дайджесты пока не отправлялись.")
        return "\n".join(lines)

    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        sent_at = escape(str(item.get("sent_at") or "—"))
        format_name = escape(str(item.get("format") or "—"))
        preview = str(item.get("text_preview") or "").strip()
        lines.append(f"• {sent_at} · {format_name}")
        if preview:
            lines.append(f"  {escape(preview[:160])}")

    if len(items) < int(total or 0):
        lines.append("Больше записей доступно в web-приложении.")

    return "\n".join(lines)


@router.message(Command("digest_history"))
async def handle_digest_history(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    try:
        history = await api_client.get_digest_history(telegram_user_id, limit=5, offset=0)
    except SkillraApiError as exc:
        if exc.status_code == 404:
            await message.answer(texts.digest_profile_fallback(), reply_markup=build_menu_keyboard())
            return
        logger.exception("Failed to fetch digest history", extra={"user_id": mask_user_id(telegram_user_id)})
        await message.answer(user_message_from_error(exc, "Не удалось загрузить историю дайджестов."))
        return
    except Exception:  # noqa: BLE001
        logger.exception(
            "Unexpected error while fetching digest history",
            extra={"user_id": mask_user_id(telegram_user_id)},
        )
        await message.answer("Не удалось загрузить историю дайджестов. Попробуйте позже.")
        return

    await message.answer(format_digest_history_message(history), parse_mode=ParseMode.HTML)


@router.message(Command("plan"))
async def handle_plan(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    try:
        plan = await api_client.get_career_plan(telegram_user_id)
    except SkillraApiError as exc:
        error_code = exc.error_code
        if not error_code and isinstance(exc.payload, dict):
            error_code = exc.payload.get("error_code")

        if exc.status_code == 404 or error_code == "CAREER_PLAN_NOT_FOUND":
            try:
                plan = await api_client.upsert_career_plan(
                    telegram_user_id,
                    {"notes": "Создано из Telegram /plan"},
                )
            except SkillraApiError as create_exc:
                logger.exception(
                    "Failed to create career plan",
                    extra={"user_id": mask_user_id(telegram_user_id), "status": create_exc.status_code},
                )
                await message.answer(
                    user_message_from_error(
                        create_exc,
                        "Не удалось создать карьерный план. Попробуйте позже.",
                    )
                )
                return
        else:
            logger.exception(
                "Failed to fetch career plan",
                extra={"user_id": mask_user_id(telegram_user_id), "status": exc.status_code},
            )
            await message.answer(user_message_from_error(exc, "Не удалось загрузить карьерный план."))
            return
    except Exception:  # noqa: BLE001
        logger.exception(
            "Unexpected error while fetching career plan",
            extra={"user_id": mask_user_id(telegram_user_id)},
        )
        await message.answer("Не удалось загрузить карьерный план. Попробуйте позже.")
        return

    await message.answer(
        format_career_plan_message(plan),
        parse_mode=ParseMode.HTML,
        reply_markup=build_plan_actions_keyboard(plan) or build_menu_keyboard(),
    )
    track_product_event_safely(
        api_client,
        telegram_user_id,
        "plan_viewed",
        entity_type="career_plan",
        metadata={"action_count": len(plan.get("actions") if isinstance(plan.get("actions"), list) else [])},
    )


@router.callback_query(F.data.startswith(PLAN_ACTION_CALLBACK_PREFIX))
async def update_plan_action_status(callback: CallbackQuery, api_client: SkillraApiClient) -> None:
    """Update an ordinary career-plan action status from inline buttons."""

    await callback.answer()
    telegram_user_id = callback.from_user.id if callback.from_user else None
    parsed = _parse_plan_action_callback(callback.data)
    if telegram_user_id is None or callback.message is None or parsed is None:
        return

    action_id, status = parsed
    try:
        action = await api_client.patch_career_action(telegram_user_id, action_id, {"status": status})
    except SkillraApiError as exc:
        logger.exception(
            "Failed to update plan action status",
            extra={"user_id": mask_user_id(telegram_user_id), "status": exc.status_code},
        )
        await callback.message.answer(user_message_from_error(exc, "Не удалось обновить статус действия."))
        return
    except Exception:  # noqa: BLE001
        logger.exception(
            "Unexpected error while updating plan action status",
            extra={"user_id": mask_user_id(telegram_user_id)},
        )
        await callback.message.answer("Не удалось обновить статус действия. Попробуйте позже.")
        return

    title = escape(str(action.get("title") or "Действие"))
    status_label = ACTION_STATUS_LABELS.get(str(action.get("status") or status), status)
    await callback.message.answer(
        f"Статус обновлён: <b>{escape(status_label)}</b> — {title}.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("plan_recommend"))
async def handle_plan_recommend(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    try:
        try:
            await api_client.get_career_plan(telegram_user_id)
        except SkillraApiError as exc:
            error_code = exc.error_code
            if not error_code and isinstance(exc.payload, dict):
                error_code = exc.payload.get("error_code")
            if exc.status_code != 404 and error_code != "CAREER_PLAN_NOT_FOUND":
                raise
            await api_client.upsert_career_plan(
                telegram_user_id,
                {"notes": "Создано из Telegram /plan_recommend"},
            )

        plan = await api_client.generate_career_plan_actions(
            telegram_user_id,
            limit=5,
            replace_generated=False,
        )
    except SkillraApiError as exc:
        logger.exception(
            "Failed to generate career plan actions",
            extra={"user_id": mask_user_id(telegram_user_id), "status": exc.status_code},
        )
        await message.answer(
            user_message_from_error(
                exc,
                "Не удалось добавить рекомендации в карьерный план. Проверьте профиль и попробуйте позже.",
            )
        )
        return
    except Exception:  # noqa: BLE001
        logger.exception(
            "Unexpected error while generating career plan actions",
            extra={"user_id": mask_user_id(telegram_user_id)},
        )
        await message.answer("Не удалось добавить рекомендации в карьерный план. Попробуйте позже.")
        return

    await message.answer(
        "Рекомендации из skill gap добавлены.\n\n" + format_career_plan_message(plan),
        parse_mode=ParseMode.HTML,
        reply_markup=build_plan_actions_keyboard(plan) or build_menu_keyboard(),
    )


@router.message(Command("status"))
async def handle_status(message: Message, api_client: SkillraApiClient) -> None:
    telegram_user_id = message.from_user.id if message.from_user else None
    extra_log = {"user_id": mask_user_id(telegram_user_id)}

    service_health: dict[str, Any] | None = None
    data_health: dict[str, Any] | None = None
    data_error: str | None = None
    due_count: int | None = None

    try:
        service_health = await api_client.service_health()
    except httpx.HTTPError:
        logger.exception("Failed to fetch /health", extra=extra_log)

    try:
        data_health = await api_client.data_health()
    except SkillraApiError as exc:
        status = exc.status_code
        data_error = (
            user_message_from_error(exc, f"/v1/health вернул {status}") if status else "Ошибка при запросе /v1/health"
        )
        logger.warning("/v1/health returned error", extra={**extra_log, "status": status})
        try:
            data_health = exc.payload if isinstance(exc.payload, dict) else None
        except Exception:  # noqa: BLE001
            data_health = None
    except httpx.HTTPError:
        data_error = "Не удалось подключиться к /v1/health"
        logger.exception("Failed to fetch /v1/health", extra=extra_log)
    except Exception:  # noqa: BLE001
        data_error = "Неожиданная ошибка при запросе /v1/health"
        logger.exception("Unexpected error while fetching /v1/health", extra=extra_log)

    try:
        due_subscriptions = await api_client.get_due_subscriptions()
        due_count = len(due_subscriptions)
    except SkillraApiError as exc:
        logger.warning("Failed to fetch due subscriptions", extra={**extra_log, "status": exc.status_code})
    except httpx.HTTPError:
        logger.exception("Failed to fetch due subscriptions", extra=extra_log)
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error while fetching due subscriptions", extra=extra_log)

    await message.answer(format_status_message(service_health, data_health, data_error, due_count))


@router.message(Command("account"))
async def show_account(message: Message, api_client: SkillraApiClient) -> None:
    """Sprint-007 TASK-05: Show combined profile + subscription overview."""

    telegram_user_id = message.from_user.id if message.from_user else None
    if telegram_user_id is None:
        await message.answer(texts.cannot_determine_user())
        return

    lines: list[str] = ["👤 <b>Аккаунт</b>"]

    try:
        next_action = await api_client.get_next_best_action(telegram_user_id, source="bot")
    except SkillraApiError:
        next_action = None
    except Exception:  # noqa: BLE001
        logger.exception("Failed to fetch account next best action", extra={"user_id": mask_user_id(telegram_user_id)})
        next_action = None

    if next_action:
        lines.append(format_next_best_action_message(next_action))
        lines.append("")

    try:
        commercial_state = await api_client.get_commercial_state(telegram_user_id)
        lines.extend(format_commercial_state_message(commercial_state))
    except SkillraApiError:
        lines.append("💳 Тариф: временно недоступен. Базовые функции работают.")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to fetch commercial state", extra={"user_id": mask_user_id(telegram_user_id)})
        lines.append("💳 Тариф: временно недоступен. Базовые функции работают.")

    lines.append("")

    # Load profile
    try:
        profile = await api_client.get_profile(telegram_user_id)
        role = escape(profile.get("target_role") or "не указана")
        grade = escape(profile.get("target_grade") or "не указан")
        skills = profile.get("current_skills", [])
        skills_preview = escape(", ".join(skills[:5])) + (f" (+{len(skills) - 5})" if len(skills) > 5 else "")
        lines.append(f"Роль: <b>{role}</b> | {grade}")
        lines.append(f"Навыки: {skills_preview or '—'}")
    except SkillraApiError:
        lines.append("Профиль не заполнен. Используй /profile.")

    lines.append("")

    # Load subscription
    try:
        sub = await api_client.get_weekly_subscription(telegram_user_id)
        from telegram_bot.handlers.subscriptions import (
            WEEKDAY_LABELS,
            _parse_optional_datetime,
            compute_next_send_datetime,
        )

        status = "✅ Активна" if sub.get("active") else "⏸ На паузе"
        weekday_idx = sub.get("weekday", 0)
        weekday_label = WEEKDAY_LABELS[weekday_idx] if 0 <= weekday_idx < 7 else "—"
        time_local = escape(sub.get("time_local") or "—")
        timezone_name = sub.get("timezone") or "UTC"
        timezone = escape(timezone_name)
        lines.append(f"🔔 Подписка: {status}")
        lines.append(f"Каждый {weekday_label} в {time_local} ({timezone})")
        next_send = compute_next_send_datetime(
            int(sub.get("weekday", 0)),
            str(sub.get("time_local") or "09:00"),
            str(timezone_name),
            _parse_optional_datetime(sub.get("last_sent_at")),
        )
        lines.append(f"Следующий: {next_send.strftime('%d.%m.%Y %H:%M')} UTC")
    except SkillraApiError as exc:
        if exc.status_code == 404:
            lines.append("🔕 Подписка не оформлена. Используй /subscribe.")
        else:
            lines.append("Не удалось загрузить подписку.")

    await message.answer("\n".join(lines), parse_mode="HTML")
