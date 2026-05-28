"""Handler for vacancy search commands."""

from __future__ import annotations

import logging
import time
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telegram_bot.services.api_client import SkillraApiClient
from telegram_bot.services.callback_context import CallbackContextError, CallbackContextStore
from telegram_bot.services.errors import SkillraApiError, user_message_from_error

logger = logging.getLogger(__name__)
router = Router()

RESULTS_PER_PAGE = 5
SAVE_CALLBACK_PREFIX = "vac:save:"
OUTCOME_CALLBACK_PREFIX = "vac:out:"
SEARCH_CALLBACK_NAMESPACE = "srch"
SEARCH_SAVE_ACTION = "save"
SEARCH_OUTCOME_ACTION = "outcome"
DURABLE_SAVE_CALLBACK_PREFIX = f"{SEARCH_CALLBACK_NAMESPACE}:{SEARCH_SAVE_ACTION}:"
DURABLE_OUTCOME_CALLBACK_PREFIX = f"{SEARCH_CALLBACK_NAMESPACE}:{SEARCH_OUTCOME_ACTION}:"
OUTCOME_LABELS = {
    "applied": "Откликнулся",
    "interview": "Интервью",
    "offer": "Оффер",
    "rejected": "Отказ",
    "withdrawn": "Снято",
}
SEARCH_RESULT_CACHE_TTL_SECONDS = 15 * 60
SEARCH_RESULT_CACHE_MAX_USERS = 512
_SEARCH_RESULT_CACHE: dict[int, dict[str, Any]] = {}


@router.message(Command("search"))
async def handle_search(
    message: Message,
    api_client: SkillraApiClient,
    callback_context: CallbackContextStore | None = None,
) -> None:
    """Search vacancies via Skillra API."""

    query = _extract_search_query(message.text)
    if not query:
        await message.answer(
            "<b>Поиск вакансий</b>\n\n"
            "Использование: <code>/search Python Data Analyst</code>\n"
            "Поиск по названию, описанию и навыкам."
        )
        return

    telegram_user_id = message.from_user.id if message.from_user else None
    filters = await _profile_search_filters(api_client, telegram_user_id)
    if telegram_user_id is not None:
        filters["telegram_user_id"] = telegram_user_id
        filters["source"] = "bot"
    try:
        search_payload = await api_client.search_vacancies_payload(q=query, limit=RESULTS_PER_PAGE, **filters)
    except Exception:  # noqa: BLE001
        logger.exception("Vacancy search failed")
        await message.answer("Поиск временно недоступен. Попробуйте позже.")
        return

    vacancies = _payload_results(search_payload)
    reply_markup = None
    if telegram_user_id is not None:
        _cache_search_results(telegram_user_id, vacancies)
        reply_markup = await build_durable_search_results_keyboard(vacancies, telegram_user_id, callback_context)

    await message.answer(
        format_search_results(query, vacancies, search_payload),
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith(DURABLE_SAVE_CALLBACK_PREFIX))
@router.callback_query(F.data.startswith(SAVE_CALLBACK_PREFIX))
async def save_search_vacancy(
    callback: CallbackQuery,
    api_client: SkillraApiClient,
    callback_context: CallbackContextStore | None = None,
) -> None:
    """Save a previously shown search result into the user's career plan."""

    await callback.answer()
    telegram_user_id = callback.from_user.id if callback.from_user else None
    if telegram_user_id is None or callback.message is None:
        return

    vacancy, cache_state = await _resolve_save_callback(callback.data, telegram_user_id, callback_context)
    if vacancy is None:
        if cache_state == "expired":
            await callback.message.answer("Срок действия кнопки истёк. Повторите /search и выберите вакансию заново.")
        else:
            await callback.message.answer("Повторите /search: я не нашёл эту вакансию в последней выдаче.")
        return

    payload = _saved_vacancy_payload(vacancy)
    try:
        action = await api_client.save_career_plan_vacancy(telegram_user_id, payload)
    except SkillraApiError as exc:
        if exc.status_code == 404 or exc.error_code == "CAREER_PLAN_NOT_FOUND":
            try:
                await api_client.upsert_career_plan(telegram_user_id, {"notes": "Создано из Telegram /search"})
                action = await api_client.save_career_plan_vacancy(telegram_user_id, payload)
            except SkillraApiError as create_exc:
                logger.exception("Failed to create career plan before saving vacancy")
                await callback.message.answer(
                    user_message_from_error(
                        create_exc,
                        "Не удалось создать карьерный план и сохранить вакансию.",
                    )
                )
                return
        else:
            logger.exception("Failed to save vacancy from Telegram search")
            await callback.message.answer(user_message_from_error(exc, "Не удалось сохранить вакансию."))
            return
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error while saving vacancy from Telegram search")
        await callback.message.answer("Не удалось сохранить вакансию. Попробуйте позже.")
        return

    action_id = action.get("id")
    reply_markup = None
    if action_id is not None:
        reply_markup = await build_durable_outcome_keyboard(int(action_id), telegram_user_id, callback_context)
    await callback.message.answer(
        format_saved_vacancy_message(action),
        reply_markup=reply_markup,
    )


@router.callback_query(F.data.startswith(DURABLE_OUTCOME_CALLBACK_PREFIX))
@router.callback_query(F.data.startswith(OUTCOME_CALLBACK_PREFIX))
async def update_search_vacancy_outcome(
    callback: CallbackQuery,
    api_client: SkillraApiClient,
    callback_context: CallbackContextStore | None = None,
) -> None:
    """Update application outcome for a saved vacancy action."""

    await callback.answer()
    telegram_user_id = callback.from_user.id if callback.from_user else None
    if telegram_user_id is None or callback.message is None:
        return

    parsed, callback_state = await _resolve_outcome_callback(callback.data, telegram_user_id, callback_context)
    if parsed is None:
        if _parse_durable_callback(callback.data, SEARCH_CALLBACK_NAMESPACE, SEARCH_OUTCOME_ACTION):
            if callback_state == "expired":
                await callback.message.answer("Срок действия кнопки истёк. Откройте /plan или повторите /search.")
            else:
                await callback.message.answer("Не удалось проверить кнопку. Откройте /plan или повторите /search.")
        return

    action_id, status = parsed
    try:
        action = await api_client.update_application_outcome(telegram_user_id, action_id, status, source="bot")
    except SkillraApiError as exc:
        logger.exception("Failed to update vacancy outcome from Telegram")
        await callback.message.answer(user_message_from_error(exc, "Не удалось обновить статус отклика."))
        return
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error while updating vacancy outcome from Telegram")
        await callback.message.answer("Не удалось обновить статус отклика. Попробуйте позже.")
        return

    label = OUTCOME_LABELS.get(str(action.get("application_status") or status), status)
    title = action.get("vacancy_title") or action.get("title") or "вакансия"
    await callback.message.answer(f"Статус обновлён: <b>{escape(label)}</b> — {escape(str(title))}.")


def format_search_results(
    query: str,
    vacancies: list[dict[str, Any]],
    search_payload: dict[str, Any] | None = None,
) -> str:
    """Format vacancy search results for Telegram HTML output."""

    safe_query = escape(query)
    if not vacancies:
        return f"По запросу <b>{safe_query}</b> ничего не найдено."

    lines = [f"<b>Результаты по запросу {safe_query}</b>:"]
    trust_line = _format_search_trust(search_payload or {})
    if trust_line:
        lines.append(trust_line)
    for index, vacancy in enumerate(vacancies[:RESULTS_PER_PAGE], start=1):
        title = escape(str(vacancy.get("title") or "Без названия"))
        employer = escape(str(vacancy.get("employer") or vacancy.get("company") or ""))
        city = escape(str(vacancy.get("city") or ""))
        salary = _format_salary(vacancy)
        url = vacancy.get("hh_url") or vacancy.get("url")
        skills = vacancy.get("skills") if isinstance(vacancy.get("skills"), list) else []
        fit_reason = vacancy.get("fit_reason")
        gap_reason = vacancy.get("gap_reason")
        plan_relevance = vacancy.get("plan_relevance")
        match_score = vacancy.get("match_score")
        match_level = vacancy.get("match_level")

        details = " · ".join(part for part in (employer, city, salary) if part)
        lines.append(f"\n{index}. <b>{title}</b>")
        if isinstance(match_score, int):
            lines.append(f"Матч: <b>{match_score}%</b> · {_match_level_label(match_level)}")
        if details:
            lines.append(details)
        if skills:
            lines.append("Навыки: " + ", ".join(escape(str(skill)) for skill in skills[:5]))
        if fit_reason:
            lines.append(f"Почему подходит: {escape(str(fit_reason))}")
        if gap_reason:
            lines.append(f"Что подтянуть: {escape(str(gap_reason))}")
        if plan_relevance:
            lines.append(f"Связь с планом: {escape(str(plan_relevance))}")
        if url:
            lines.append(f'<a href="{escape(str(url), quote=True)}">Открыть на hh.ru</a>')

    return "\n".join(lines)


def build_search_results_keyboard(vacancies: list[dict[str, Any]]):
    builder = InlineKeyboardBuilder()
    has_buttons = False
    for index, vacancy in enumerate(vacancies[:RESULTS_PER_PAGE], start=1):
        vacancy_id = str(vacancy.get("hh_vacancy_id") or "").strip()
        if not vacancy_id:
            continue
        builder.button(text=f"Сохранить {index}", callback_data=f"{SAVE_CALLBACK_PREFIX}{vacancy_id}")
        has_buttons = True
    builder.adjust(1)
    return builder.as_markup() if has_buttons else None


async def build_durable_search_results_keyboard(
    vacancies: list[dict[str, Any]],
    telegram_user_id: int,
    callback_context: CallbackContextStore | None,
):
    if callback_context is None or not callback_context.available:
        return build_search_results_keyboard(vacancies)

    builder = InlineKeyboardBuilder()
    has_buttons = False
    try:
        for index, vacancy in enumerate(vacancies[:RESULTS_PER_PAGE], start=1):
            payload = _saved_vacancy_payload(vacancy)
            vacancy_id = str(payload.get("hh_vacancy_id") or "").strip()
            if not vacancy_id:
                continue
            callback_data = await callback_context.create_callback_data(
                namespace=SEARCH_CALLBACK_NAMESPACE,
                action=SEARCH_SAVE_ACTION,
                user_id=telegram_user_id,
                entity_type="vacancy",
                entity_id=vacancy_id,
                payload=payload,
                ttl_seconds=SEARCH_RESULT_CACHE_TTL_SECONDS,
            )
            builder.button(text=f"Сохранить {index}", callback_data=callback_data)
            has_buttons = True
    except CallbackContextError:
        logger.warning("Durable search callbacks unavailable; falling back to legacy callback data")
        return build_search_results_keyboard(vacancies)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to create durable search callbacks; falling back to legacy callback data")
        return build_search_results_keyboard(vacancies)

    builder.adjust(1)
    return builder.as_markup() if has_buttons else None


def build_outcome_keyboard(action_id: int):
    builder = InlineKeyboardBuilder()
    for status, label in OUTCOME_LABELS.items():
        builder.button(text=label, callback_data=f"{OUTCOME_CALLBACK_PREFIX}{action_id}:{status}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


async def build_durable_outcome_keyboard(
    action_id: int,
    telegram_user_id: int,
    callback_context: CallbackContextStore | None,
):
    if callback_context is None or not callback_context.available:
        return build_outcome_keyboard(action_id)

    builder = InlineKeyboardBuilder()
    try:
        for status, label in OUTCOME_LABELS.items():
            callback_data = await callback_context.create_callback_data(
                namespace=SEARCH_CALLBACK_NAMESPACE,
                action=SEARCH_OUTCOME_ACTION,
                user_id=telegram_user_id,
                entity_type="career_action",
                entity_id=str(action_id),
                payload={"action_id": action_id, "status": status},
                ttl_seconds=SEARCH_RESULT_CACHE_TTL_SECONDS,
            )
            builder.button(text=label, callback_data=callback_data)
    except CallbackContextError:
        logger.warning("Durable outcome callbacks unavailable; falling back to legacy callback data")
        return build_outcome_keyboard(action_id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to create durable outcome callbacks; falling back to legacy callback data")
        return build_outcome_keyboard(action_id)

    builder.adjust(2, 2, 1)
    return builder.as_markup()


def format_saved_vacancy_message(action: dict[str, Any]) -> str:
    title = action.get("vacancy_title") or action.get("title") or "вакансия"
    return (
        "<b>Вакансия сохранена в карьерный план</b>\n"
        f"{escape(str(title))}\n"
        "Дальше можно обновлять статус отклика кнопками ниже."
    )


def _extract_search_query(text: str | None) -> str:
    if not text:
        return ""

    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


async def _profile_search_filters(api_client: SkillraApiClient, telegram_user_id: int | None) -> dict[str, object]:
    if telegram_user_id is None:
        return {}
    try:
        profile = await api_client.get_profile(telegram_user_id)
    except SkillraApiError as exc:
        if exc.status_code != 404:
            logger.warning("Failed to load profile for vacancy search", extra={"status": exc.status_code})
        return {}
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error while loading profile for vacancy search")
        return {}

    mapping = {
        "role": profile.get("target_role"),
        "grade": profile.get("target_grade"),
        "country": profile.get("target_country"),
        "region": profile.get("target_region"),
        "city": profile.get("target_city"),
        "geo_scope": profile.get("target_geo_scope"),
    }
    return {key: str(value) for key, value in mapping.items() if value}


def _match_level_label(level: object) -> str:
    mapping = {
        "high": "сильный",
        "medium": "средний",
        "low": "низкий",
        "unknown": "неточно",
    }
    return mapping.get(str(level), "неточно")


def _payload_results(search_payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = search_payload.get("results", search_payload.get("hits", []))
    return results if isinstance(results, list) else []


def _cache_search_results(telegram_user_id: int, vacancies: list[dict[str, Any]]) -> None:
    now = time.time()
    _prune_search_cache(now)
    cached: dict[str, dict[str, Any]] = {}
    for vacancy in vacancies[:RESULTS_PER_PAGE]:
        vacancy_id = str(vacancy.get("hh_vacancy_id") or "").strip()
        if vacancy_id:
            cached[vacancy_id] = vacancy
    _SEARCH_RESULT_CACHE[telegram_user_id] = {"cached_at": now, "vacancies": cached}
    _prune_search_cache(now)


def _get_cached_search_vacancy(
    telegram_user_id: int,
    vacancy_id: str,
    *,
    now: float | None = None,
) -> tuple[dict[str, Any] | None, str]:
    current_time = time.time() if now is None else now
    entry = _SEARCH_RESULT_CACHE.get(telegram_user_id)
    if not entry:
        return None, "missing"

    cached_at = entry.get("cached_at")
    vacancies = entry.get("vacancies")
    if not isinstance(vacancies, dict):
        vacancies = entry
        cached_at = current_time

    if isinstance(cached_at, (int, float)) and current_time - float(cached_at) > SEARCH_RESULT_CACHE_TTL_SECONDS:
        _SEARCH_RESULT_CACHE.pop(telegram_user_id, None)
        return None, "expired"

    vacancy = vacancies.get(vacancy_id)
    return (vacancy, "hit") if isinstance(vacancy, dict) else (None, "missing")


async def _resolve_save_callback(
    data: str | None,
    telegram_user_id: int,
    callback_context: CallbackContextStore | None,
) -> tuple[dict[str, Any] | None, str]:
    token = _parse_durable_callback(data, SEARCH_CALLBACK_NAMESPACE, SEARCH_SAVE_ACTION)
    if token:
        context, state = await _resolve_context(
            callback_context,
            namespace=SEARCH_CALLBACK_NAMESPACE,
            action=SEARCH_SAVE_ACTION,
            token=token,
            telegram_user_id=telegram_user_id,
        )
        if context is None:
            return None, state
        vacancy = context.payload
        return (vacancy, "hit") if vacancy.get("hh_vacancy_id") else (None, "missing")

    vacancy_id = _parse_save_callback(data)
    if not vacancy_id:
        return None, "missing"
    return _get_cached_search_vacancy(telegram_user_id, vacancy_id)


async def _resolve_outcome_callback(
    data: str | None,
    telegram_user_id: int,
    callback_context: CallbackContextStore | None,
) -> tuple[tuple[int, str] | None, str]:
    token = _parse_durable_callback(data, SEARCH_CALLBACK_NAMESPACE, SEARCH_OUTCOME_ACTION)
    if token:
        context, state = await _resolve_context(
            callback_context,
            namespace=SEARCH_CALLBACK_NAMESPACE,
            action=SEARCH_OUTCOME_ACTION,
            token=token,
            telegram_user_id=telegram_user_id,
        )
        if context is None:
            return None, state
        status = str(context.payload.get("status") or "")
        raw_action_id = context.payload.get("action_id") or context.entity_id
        if status not in OUTCOME_LABELS:
            return None, "missing"
        try:
            return (int(raw_action_id), status), "hit"
        except (TypeError, ValueError):
            return None, "missing"

    parsed = _parse_outcome_callback(data)
    return (parsed, "hit") if parsed is not None else (None, "missing")


async def _resolve_context(
    callback_context: CallbackContextStore | None,
    *,
    namespace: str,
    action: str,
    token: str,
    telegram_user_id: int,
) -> tuple[Any | None, str]:
    if callback_context is None:
        return None, "missing"
    try:
        return await callback_context.resolve(
            namespace=namespace,
            action=action,
            token=token,
            user_id=telegram_user_id,
        ), "hit"
    except CallbackContextError as exc:
        return None, "expired" if exc.reason == "expired" else "missing"


def _prune_search_cache(now: float) -> None:
    expired_user_ids: list[int] = []
    for user_id, entry in _SEARCH_RESULT_CACHE.items():
        cached_at = entry.get("cached_at")
        if isinstance(cached_at, (int, float)) and now - float(cached_at) > SEARCH_RESULT_CACHE_TTL_SECONDS:
            expired_user_ids.append(user_id)
    for user_id in expired_user_ids:
        _SEARCH_RESULT_CACHE.pop(user_id, None)

    overflow = len(_SEARCH_RESULT_CACHE) - SEARCH_RESULT_CACHE_MAX_USERS
    if overflow <= 0:
        return
    ordered = sorted(
        _SEARCH_RESULT_CACHE.items(),
        key=lambda item: item[1].get("cached_at") if isinstance(item[1].get("cached_at"), (int, float)) else now,
    )
    for user_id, _ in ordered[:overflow]:
        _SEARCH_RESULT_CACHE.pop(user_id, None)


def _saved_vacancy_payload(vacancy: dict[str, Any]) -> dict[str, Any]:
    return {
        "hh_vacancy_id": str(vacancy.get("hh_vacancy_id") or ""),
        "title": str(vacancy.get("title") or "Вакансия"),
        "url": vacancy.get("hh_url") or vacancy.get("url"),
    }


def _parse_save_callback(data: str | None) -> str | None:
    if not data or not data.startswith(SAVE_CALLBACK_PREFIX):
        return None
    vacancy_id = data.removeprefix(SAVE_CALLBACK_PREFIX).strip()
    return vacancy_id or None


def _parse_outcome_callback(data: str | None) -> tuple[int, str] | None:
    if not data or not data.startswith(OUTCOME_CALLBACK_PREFIX):
        return None
    raw = data.removeprefix(OUTCOME_CALLBACK_PREFIX)
    raw_action_id, separator, status = raw.partition(":")
    if not separator or status not in OUTCOME_LABELS:
        return None
    try:
        return int(raw_action_id), status
    except ValueError:
        return None


def _parse_durable_callback(data: str | None, namespace: str, action: str) -> str | None:
    prefix = f"{namespace}:{action}:"
    if not data or not data.startswith(prefix):
        return None
    token = data.removeprefix(prefix).strip()
    return token or None


def _format_search_trust(payload: dict[str, Any]) -> str | None:
    parts: list[str] = []
    confidence = _confidence_label(payload.get("confidence"))
    if confidence:
        parts.append(f"доверие <b>{confidence}</b>")
    index_status = payload.get("index_status")
    if index_status:
        parts.append(f"индекс <b>{escape(str(index_status))}</b>")
    dataset_run_id = payload.get("dataset_run_id")
    index_dataset_run_id = payload.get("index_dataset_run_id")
    if dataset_run_id:
        parts.append(f"данные <code>{escape(str(dataset_run_id))}</code>")
    if index_dataset_run_id and index_dataset_run_id != dataset_run_id:
        parts.append(f"индекс-данные <code>{escape(str(index_dataset_run_id))}</code>")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    if warnings:
        parts.append("есть предупреждения")
    return "Надёжность поиска: " + " | ".join(parts) if parts else None


def _confidence_label(value: Any) -> str | None:
    if value == "high":
        return "высокое"
    if value == "medium":
        return "среднее"
    if value == "low":
        return "низкое"
    return None


def _format_salary(vacancy: dict[str, Any]) -> str:
    salary_from = vacancy.get("salary_from")
    salary_to = vacancy.get("salary_to")

    if salary_from and salary_to:
        return f"{_format_money(salary_from)}-{_format_money(salary_to)} ₽"
    if salary_from:
        return f"от {_format_money(salary_from)} ₽"
    if salary_to:
        return f"до {_format_money(salary_to)} ₽"
    return ""


def _format_money(value: Any) -> str:
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)
