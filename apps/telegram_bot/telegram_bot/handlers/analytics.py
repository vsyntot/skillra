from __future__ import annotations

import asyncio
import logging
import shlex
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telegram_bot import texts
from telegram_bot.handlers.commands import build_menu_keyboard
from telegram_bot.services.api_client import SkillraApiClient, track_product_event_safely
from telegram_bot.services.errors import SkillraApiError, user_message_from_error
from telegram_bot.services.meta_cache import MetaCache
from telegram_bot.services.skills import (
    build_skill_suggestions,
    format_unknown_skills_message,
    normalize_skill_name,
)

logger = logging.getLogger(__name__)

router = Router()


class AdHocAnalysis(StatesGroup):
    """Sprint-007 TASK-04: Ad-hoc analysis FSM states."""

    role = State()
    grade = State()


@router.message(Command("market"))
@router.message(F.text.casefold() == "карта рынка")
async def handle_market_map(message: Message, api_client: SkillraApiClient, meta_cache: MetaCache) -> None:
    profile = await _load_profile(message, api_client)
    if not profile or (error := _profile_validation_error(profile)):
        if error:
            await message.answer(error)
        return

    filters = build_market_filters(profile)
    try:
        summary = await api_client.market_segment_summary(filters)
    except SkillraApiError as exc:
        logger.exception("Failed to fetch market summary")
        await message.answer(
            await _format_analytics_error_message(
                exc,
                api_client,
                meta_cache,
                default_message="Не удалось получить карту рынка. Попробуйте позже.",
            )
        )
        return

    await message.answer(format_market_summary(profile, summary))
    telegram_user_id = message.from_user.id if message.from_user else None
    track_product_event_safely(
        api_client,
        telegram_user_id,
        "market_fit_viewed",
        entity_type="market_segment",
        metadata={
            "dataset_run_id": summary.get("dataset_run_id"),
            "confidence": summary.get("confidence"),
            "freshness": summary.get("freshness"),
            "vacancy_count": summary.get("vacancy_count"),
        },
    )


@router.message(Command("skillgap"))
@router.message(F.text.casefold() == "skill-gap")
async def handle_skill_gap(message: Message, api_client: SkillraApiClient, meta_cache: MetaCache) -> None:
    profile = await _load_profile(message, api_client)
    if not profile or (error := _profile_validation_error(profile)):
        if error:
            await message.answer(error)
        return

    persona_payload = build_persona_payload(profile, username=message.from_user.username if message.from_user else None)

    try:
        analysis = await api_client.persona_analyze(persona_payload)
    except SkillraApiError as exc:
        logger.exception("Failed to analyze persona")
        await message.answer(
            await _format_analytics_error_message(
                exc,
                api_client,
                meta_cache,
                default_message="Не удалось получить skill-gap. Попробуйте позже.",
            )
        )
        return

    await message.answer(format_skill_gap_report(analysis))
    telegram_user_id = message.from_user.id if message.from_user else None
    market_summary = analysis.get("market_summary") if isinstance(analysis.get("market_summary"), dict) else {}
    track_product_event_safely(
        api_client,
        telegram_user_id,
        "skill_gap_viewed",
        entity_type="skill_gap",
        metadata={
            "dataset_run_id": market_summary.get("dataset_run_id"),
            "confidence": market_summary.get("confidence"),
            "freshness": market_summary.get("freshness"),
            "recommended_count": len(analysis.get("recommended_skills") or []),
        },
    )

    try:
        chart_bytes = await api_client.persona_skill_gap_chart(persona_payload)
    except SkillraApiError:
        logger.exception("Failed to fetch skill-gap chart")
        await message.answer("Не удалось загрузить график skill-gap.")
        return

    await message.answer_photo(BufferedInputFile(chart_bytes, filename="skill_gap.png"), caption="Skill-gap график")


@router.message(Command("trends"))
async def handle_trends(message: Message, api_client: SkillraApiClient, meta_cache: MetaCache) -> None:
    profile = await _load_profile(message, api_client)
    if not profile or (error := _profile_validation_error(profile)):
        if error:
            await message.answer(error)
        return

    role = str(profile.get("target_role") or "").strip()
    grade = str(profile.get("target_grade") or "").strip()
    if not grade:
        await message.answer("Профиль неполный: укажите грейд через /settings.")
        return

    filters = build_market_filters(profile)
    salary_result: dict[str, Any] | Exception
    vacancy_result: dict[str, Any] | Exception
    summary_result: dict[str, Any] | Exception
    graph_result: dict[str, Any] | Exception
    try:
        salary_result, vacancy_result, summary_result, graph_result = await asyncio.gather(
            api_client.salary_trend(role, grade),
            api_client.vacancy_count_trend(role, grade=grade),
            api_client.market_segment_summary(filters),
            api_client.career_graph(role),
            return_exceptions=True,
        )
    except SkillraApiError as exc:
        logger.exception("Failed to fetch market trends")
        await message.answer(
            await _format_analytics_error_message(
                exc,
                api_client,
                meta_cache,
                default_message="Не удалось получить тренды. Попробуйте позже.",
            )
        )
        return

    core_results = [salary_result, vacancy_result, summary_result, graph_result]
    if all(isinstance(result, Exception) for result in core_results):
        first_error = next(result for result in core_results if isinstance(result, Exception))
        if isinstance(first_error, SkillraApiError):
            await message.answer(
                await _format_analytics_error_message(
                    first_error,
                    api_client,
                    meta_cache,
                    default_message="Не удалось получить тренды. Попробуйте позже.",
                )
            )
        else:
            logger.error("Failed to fetch market trends", extra={"error_type": first_error.__class__.__name__})
            await message.answer("Не удалось получить тренды. Попробуйте позже.")
        return

    top_skills = []
    if isinstance(summary_result, dict):
        top_skills = [str(skill) for skill in (summary_result.get("top_skills") or []) if skill]

    skill_results: list[dict[str, Any] | Exception] = []
    for skill in top_skills[:3]:
        try:
            skill_results.append(await api_client.skill_demand_trend(skill, role=role, grade=grade))
        except Exception as exc:  # noqa: BLE001
            skill_results.append(exc)

    await message.answer(
        format_trends_report(
            profile,
            salary_result if isinstance(salary_result, dict) else None,
            vacancy_result if isinstance(vacancy_result, dict) else None,
            [result for result in skill_results if isinstance(result, dict)],
            graph_result if isinstance(graph_result, dict) else None,
        )
    )


def format_market_summary(profile: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = ["<b>Карта рынка</b>"]
    lines.append(_format_filters_line(profile))
    lines.append(f"Вакансий в сегменте: <b>{summary.get('vacancy_count', 0)}</b>")

    salary_median = summary.get("salary_median")
    if salary_median is None:
        lines.append("Зарплаты: данных пока нет.")
    else:
        lines.append(
            "Зарплаты: медиана "
            f"<b>{_format_salary(summary.get('salary_median'))}</b> "
            f"(Q25 {_format_salary(summary.get('salary_q25'))}, Q75 {_format_salary(summary.get('salary_q75'))})"
        )

    lines.append(
        "Удалёнка: "
        f"<b>{_format_percent(summary.get('remote_share'))}</b> | "
        f"Junior-friendly: <b>{_format_percent(summary.get('junior_friendly_share'))}</b>"
    )

    confidence = _format_confidence(summary.get("confidence"))
    salary_coverage = _format_percent(summary.get("salary_coverage_share"))
    salary_sample = _format_sample(
        summary.get("salary_sample_size"), summary.get("sample_size") or summary.get("vacancy_count")
    )
    if confidence or salary_coverage != "—":
        trust_parts = []
        if confidence:
            trust_parts.append(f"доверие <b>{confidence}</b>")
        if salary_coverage != "—":
            trust_parts.append(f"покрытие зарплат <b>{salary_coverage}</b>{salary_sample}")
        lines.append("Надёжность оценки: " + " | ".join(trust_parts))

    if summary.get("median_tech_stack_size") is not None:
        lines.append(f"Средний размер стека: <b>{float(summary['median_tech_stack_size']):.1f}</b> навыков")

    top_skills = summary.get("top_skills") or []
    if top_skills:
        lines.append("Топ навыков сегмента:")
        lines.extend(f"• {escape(skill)}" for skill in top_skills[:5])

    warnings = summary.get("warnings") or []
    if warnings:
        lines.append("⚠️ Предупреждения:")
        lines.extend(f"• {escape(text)}" for text in warnings)

    return "\n".join(lines)


def format_trends_report(
    profile: dict[str, Any],
    salary_trend: dict[str, Any] | None,
    vacancy_trend: dict[str, Any] | None,
    skill_trends: list[dict[str, Any]],
    career_graph: dict[str, Any] | None,
) -> str:
    lines = ["<b>Тренды рынка</b>"]
    lines.append(_format_filters_line(profile))
    blocked_warning = _trend_block_warning([salary_trend, vacancy_trend, *skill_trends])
    if blocked_warning:
        lines.append(blocked_warning)
        lines.append("Используйте /market как текущий снимок рынка без исторических выводов.")
        return "\n".join(lines)

    lines.append(_format_trend_line("Зарплата P50", salary_trend, value_formatter=_format_salary))
    lines.append(_format_trend_line("Вакансии", vacancy_trend, value_formatter=_format_count))

    if skill_trends:
        lines.append("Спрос на навыки:")
        for trend in skill_trends[:3]:
            skill = escape(str(trend.get("skill") or "Навык"))
            lines.append("• " + _format_trend_line(skill, trend, value_formatter=_format_count, empty="нет данных"))

    transitions = (career_graph or {}).get("transitions") or []
    if transitions:
        lines.append("Карьерный граф:")
        for transition in transitions[:3]:
            from_grade = escape(str(transition.get("from_grade") or "—"))
            to_grade = escape(str(transition.get("to_grade") or "—"))
            delta = _format_percent_like(transition.get("salary_delta_pct"))
            demand = _translate_demand_trend(str(transition.get("demand_trend") or ""))
            skills = [str(skill) for skill in (transition.get("skills_to_add") or []) if skill]
            skill_suffix = f"; навыки: {escape(', '.join(skills[:3]))}" if skills else ""
            lines.append(f"• {from_grade} → {to_grade}: ∆ зарплаты {delta}, спрос {demand}{skill_suffix}")
    else:
        lines.append("Карьерный граф: переходы пока не рассчитаны.")

    return "\n".join(lines)


def _trend_block_warning(payloads: list[dict[str, Any] | None]) -> str | None:
    for payload in payloads:
        if not payload or payload.get("claim_status") != "blocked":
            continue
        warnings = payload.get("warnings") or []
        if warnings:
            return str(warnings[0])
        return (
            "Историческая динамика сейчас заблокирована: нужен trend-ready датасет с подтвержденными датами "
            "публикации, достаточным числом периодов, покрытием сегментов и проверенным source capability."
        )
    return None


def format_skill_gap_report(analysis: dict[str, Any]) -> str:
    lines = ["<b>Skill-gap</b>"]
    market_summary = analysis.get("market_summary") or {}
    lines.append(
        "Сегмент: вакансий <b>{vacancies}</b>, удалёнка <b>{remote}</b>".format(
            vacancies=market_summary.get("vacancy_count", "—"),
            remote=_format_percent(market_summary.get("remote_share")),
        )
    )
    confidence = _format_confidence(market_summary.get("confidence"))
    salary_coverage = _format_percent(market_summary.get("salary_coverage_share"))
    salary_sample = _format_sample(
        market_summary.get("salary_sample_size"),
        market_summary.get("sample_size") or market_summary.get("vacancy_count"),
    )
    if confidence or salary_coverage != "—":
        trust_parts = []
        if confidence:
            trust_parts.append(f"доверие <b>{confidence}</b>")
        if salary_coverage != "—":
            trust_parts.append(f"покрытие зарплат <b>{salary_coverage}</b>{salary_sample}")
        lines.append("Надёжность оценки: " + " | ".join(trust_parts))

    recommended = analysis.get("recommended_skills") or []
    if recommended:
        lines.append("🎯 Рекомендуем прокачать:")
        lines.extend(f"• {escape(skill)}" for skill in recommended)

    top_demand = analysis.get("top_skill_demand") or []
    if top_demand:
        lines.append("🔥 Топ навыков рынка:")
        for entry in top_demand[:5]:
            share = _format_percent(entry.get("market_share"))
            lines.append(f"• {escape(entry.get('skill_name', ''))} — спрос {share}")

    skill_gap_entries = [entry for entry in (analysis.get("skill_gap") or []) if entry.get("gap")]
    if skill_gap_entries:
        lines.append("🔎 Навыки, которых не хватает:")
        for entry in skill_gap_entries[:5]:
            share = _format_percent(entry.get("market_share"))
            lines.append(f"• {escape(entry.get('skill_name', ''))} — спрос {share}")

    warnings = analysis.get("warnings") or []
    if warnings:
        lines.append("⚠️ Предупреждения:")
        lines.extend(f"• {escape(text)}" for text in warnings)

    return "\n".join(lines)


def build_market_filters(profile: dict[str, Any]) -> dict[str, Any]:
    filters = {
        "role": profile.get("target_role"),
        "grade": profile.get("target_grade"),
        "city_tier": profile.get("target_city_tier"),
        "country": profile.get("target_country"),
        "region": profile.get("target_region"),
        "city": profile.get("target_city"),
        "geo_scope": profile.get("target_geo_scope"),
        "work_mode": profile.get("target_work_mode"),
        "domain": profile.get("target_domain"),
    }
    return {key: value for key, value in filters.items() if value}


def build_persona_payload(profile: dict[str, Any], username: str | None) -> dict[str, Any]:
    persona_name = username or "Skillra пользователь"
    payload: dict[str, Any] = {
        "name": persona_name,
        "description": "Persona from Telegram profile",
        "current_skills": profile.get("current_skills", []),
        "target_role": profile.get("target_role"),
        "target_grade": profile.get("target_grade"),
        "target_city_tier": profile.get("target_city_tier"),
        "target_country": profile.get("target_country"),
        "target_region": profile.get("target_region"),
        "target_city": profile.get("target_city"),
        "target_geo_scope": profile.get("target_geo_scope"),
        "target_work_mode": profile.get("target_work_mode"),
    }

    domain = profile.get("target_domain")
    if domain:
        payload["constraints"] = {"domain": domain}

    return payload


async def _load_profile(message: Message, api_client: SkillraApiClient) -> dict[str, Any] | None:
    if not message.from_user:
        await message.answer(texts.cannot_determine_user())
        return None

    try:
        return await api_client.get_profile(message.from_user.id)
    except SkillraApiError as exc:  # noqa: PERF203
        if exc.status_code == 404:
            await message.answer(texts.analytics_profile_fallback(), reply_markup=build_menu_keyboard())
            return None
        logger.exception("Failed to load profile")
        await message.answer("Не удалось получить профиль. Попробуйте позже.")
        return None


def _profile_validation_error(profile: dict[str, Any]) -> str | None:
    if not profile.get("target_role"):
        return texts.analytics_profile_incomplete()
    return None


def _format_filters_line(profile: dict[str, Any]) -> str:
    role = escape(profile.get("target_role") or "—")
    grade = escape(profile.get("target_grade") or "—")
    city = escape(profile.get("target_city_tier") or "—")
    detailed_geo = " / ".join(
        escape(str(value))
        for value in (
            profile.get("target_country"),
            profile.get("target_region"),
            profile.get("target_city"),
            profile.get("target_geo_scope"),
        )
        if value
    )
    if detailed_geo:
        city = f"{city} ({detailed_geo})"
    work_mode = escape(profile.get("target_work_mode") or "—")
    return f"Сегмент: <b>{role}</b>, {grade}, {city}, {work_mode}"


def _format_salary(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} ₽".replace(",", " ")


def _format_count(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}".replace(",", " ")


def _format_trend_line(
    label: str,
    payload: dict[str, Any] | None,
    *,
    value_formatter: Any,
    empty: str = "данных пока нет",
) -> str:
    points = _trend_points(payload)
    if not points:
        return f"{label}: {empty}."

    first = points[0]
    latest = points[-1]
    delta = latest - first
    if abs(delta) < 1e-9:
        delta_text = "без изменений"
    else:
        sign = "+" if delta > 0 else ""
        delta_text = f"{sign}{value_formatter(delta)}"
    return f"{label}: {value_formatter(first)} → <b>{value_formatter(latest)}</b> ({delta_text})"


def _trend_points(payload: dict[str, Any] | None) -> list[float]:
    points: list[float] = []
    if not payload:
        return points

    for entry in payload.get("data") or []:
        if not isinstance(entry, dict):
            continue
        value = _to_float(entry.get("value"))
        if value is not None:
            points.append(value)
    return points


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_percent_like(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "—"
    if abs(numeric) <= 1:
        numeric *= 100
    return f"{numeric:.0f}%"


def _translate_demand_trend(value: str) -> str:
    mapping = {
        "growing": "растёт",
        "declining": "снижается",
        "stable": "стабилен",
    }
    return mapping.get(value, escape(value or "—"))


def _format_confidence(value: Any) -> str | None:
    if value == "high":
        return "высокое"
    if value == "medium":
        return "среднее"
    if value == "low":
        return "низкое"
    return None


def _format_sample(numerator: Any, denominator: Any) -> str:
    if numerator is None or denominator is None:
        return ""
    try:
        numerator_int = int(numerator)
        denominator_int = int(denominator)
    except (TypeError, ValueError):
        return ""
    return f" ({numerator_int}/{denominator_int})"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


def _lower_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower()
    return str(value).lower()


async def _format_analytics_error_message(
    exc: SkillraApiError,
    api_client: SkillraApiClient,
    meta_cache: MetaCache,
    *,
    default_message: str,
) -> str:
    payload = exc.payload
    if not isinstance(payload, dict):
        return user_message_from_error(exc, default_message)

    error_code = exc.error_code or payload.get("error_code")
    details = payload.get("details") or {}

    if error_code == "DATA_UNAVAILABLE":
        return user_message_from_error(exc, "Данные ещё не загружены. Попробуйте позже.")

    if error_code == "UNKNOWN_SKILLS":
        unknown = [normalize_skill_name(str(skill)) for skill in details.get("unknown_skills") or []]
        if unknown:
            suggestions = await build_skill_suggestions(unknown, api_client, meta_cache)
            return format_unknown_skills_message(
                unknown,
                suggestions,
                intro="Некоторые навыки неизвестны:",
                action_prompt="Откройте /settings и исправьте.",
            )
        return "Некоторые навыки неизвестны. Откройте /settings и исправьте."

    if error_code == "PROFILE_NOT_FOUND":
        return "Профиль не найден. /start"

    return user_message_from_error(exc, default_message)


# ---------------------------------------------------------------------------
# Sprint-007 TASK-04: Ad-hoc analysis without changing saved profile
# ---------------------------------------------------------------------------


@router.message(Command("analyze"))
async def start_ad_hoc_analysis(message: Message, state: FSMContext, api_client: SkillraApiClient) -> None:
    """Start ad-hoc analysis FSM — asks for role without saving to profile."""
    params = _parse_analyze_args(message.text or "")
    if params.get("role"):
        await state.clear()
        await state.update_data(ad_hoc_role=params["role"], ad_hoc_grade=params.get("grade", ""))
        await _run_ad_hoc_analysis(message, state, api_client)
        return

    await state.set_state(AdHocAnalysis.role)
    await message.answer(
        "⚡ <b>Разовый анализ</b>\n\nВведите целевую роль (например: Data Analyst):",
        parse_mode="HTML",
    )


@router.message(AdHocAnalysis.role)
async def ad_hoc_set_role(message: Message, state: FSMContext) -> None:
    role = (message.text or "").strip()
    if not role:
        await message.answer("Введите название роли.")
        return
    await state.update_data(ad_hoc_role=role)
    await state.set_state(AdHocAnalysis.grade)

    builder = InlineKeyboardBuilder()
    for grade in ["Junior", "Middle", "Senior"]:
        builder.button(text=grade, callback_data=f"adhoc:grade:{grade}")
    builder.adjust(3)

    await message.answer("Укажите грейд:", reply_markup=builder.as_markup())


@router.message(AdHocAnalysis.grade)
async def ad_hoc_set_grade_text(message: Message, state: FSMContext, api_client: SkillraApiClient) -> None:
    grade = (message.text or "").strip()
    await state.update_data(ad_hoc_grade=grade)
    await _run_ad_hoc_analysis(message, state, api_client)


from aiogram.types import CallbackQuery  # noqa: E402


@router.callback_query(AdHocAnalysis.grade, F.data.startswith("adhoc:grade:"))
async def ad_hoc_choose_grade(callback: CallbackQuery, state: FSMContext, api_client: SkillraApiClient) -> None:
    await callback.answer()
    if not callback.data or not callback.message:
        return
    grade = callback.data.removeprefix("adhoc:grade:")
    await state.update_data(ad_hoc_grade=grade)
    await _run_ad_hoc_analysis(callback.message, state, api_client)


async def _run_ad_hoc_analysis(message: Message, state: FSMContext, api_client: SkillraApiClient) -> None:
    if api_client is None:
        await message.answer("Не удалось выполнить разовый анализ: API-клиент недоступен.")
        return

    data = await state.get_data()
    role = data.get("ad_hoc_role", "")
    grade = data.get("ad_hoc_grade", "")
    await state.clear()

    # Build ad-hoc persona payload (skills empty — just market analysis)
    payload = {
        "name": "Ad-hoc",
        "description": "Разовый анализ",
        "current_skills": [],
        "target_role": role,
        "target_grade": grade or None,
    }

    try:
        result = await api_client.persona_analyze(payload)
        text = "⚡ <b>Разовый анализ</b> (профиль не изменён)\n\n" + format_skill_gap_report(result)
        await message.answer(text, parse_mode="HTML")
    except SkillraApiError as exc:
        await message.answer(user_message_from_error(exc, "Не удалось выполнить разовый анализ."))


def _parse_analyze_args(text: str) -> dict[str, str]:
    """Parse `/analyze role=... grade=...` while allowing spaces in role values."""
    raw = text.removeprefix("/analyze").strip()
    if not raw:
        return {}

    tokens = shlex.split(raw)
    result: dict[str, str] = {}
    current_key: str | None = None
    chunks: list[str] = []

    for token in tokens:
        if "=" in token and token.split("=", 1)[0] in {"role", "grade"}:
            if current_key:
                result[current_key] = " ".join(chunks).strip()
            current_key, value = token.split("=", 1)
            chunks = [value] if value else []
        elif current_key:
            chunks.append(token)

    if current_key:
        result[current_key] = " ".join(chunks).strip()

    return {key: value for key, value in result.items() if value}
