from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Iterable

import pandas as pd
from fastapi.responses import JSONResponse
from skillra_api.datastore import DataStore
from skillra_api.db.models import ApplicationOutcomeEvent, CareerAction, CareerPlan, User, UserProfile
from skillra_api.schemas import (
    DigestPreviewResponse,
    PersonaAnalysisResponse,
    PersonaProfile,
    SegmentFilters,
    SegmentSummary,
)
from skillra_api.services.analytics import compute_persona_analysis, compute_segment_summary
from skillra_api.services.trust import dataset_trust_payload

logger = logging.getLogger(__name__)

_DIGEST_BUILD_TIMEOUT_SECONDS = 30.0
_STALE_ACTION_DAYS = 14


@dataclass(frozen=True)
class DigestVacancyMatch:
    """Vacancy match rendered in the adaptive weekly digest."""

    title: str
    url: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True)
class DigestActivityContext:
    """Recent user activity used to adapt digest content."""

    last_sent_at: datetime | None = None
    event_counts: Counter[str] = field(default_factory=Counter)
    outcome_events: list[ApplicationOutcomeEvent] = field(default_factory=list)


def _format_salary(value: float | None) -> str:
    if value is None:
        return "нет данных"
    return f"{int(value):,}".replace(",", " ")


def _format_share(value: float | None) -> str:
    if value is None:
        return "нет данных"
    return f"{round(value * 100)}%"


def _bullet_list(items: Iterable[str], placeholder: str = "нет данных") -> list[str]:
    collected = list(items)
    if not collected:
        return [placeholder]
    return [f"• {escape(item)}" for item in collected]


def _status_label(status: str) -> str:
    return {
        "planned": "запланировано",
        "in_progress": "в работе",
        "done": "готово",
        "skipped": "пропущено",
    }.get(status, status)


def _career_action_text(action: CareerAction) -> str:
    suffix = f" ({_status_label(action.status)})"
    source = " · рекомендация Skillra" if getattr(action, "recommendation_source", "manual") != "manual" else ""
    outcome = f" · отклик: {action.application_status}" if getattr(action, "application_status", None) else ""
    if action.action_type == "saved_vacancy" and action.vacancy_title:
        return f"{action.vacancy_title}{suffix}{outcome}{source}"
    return f"{action.title}{suffix}{outcome}{source}"


def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _action_updated_at(action: CareerAction) -> datetime | None:
    return _ensure_aware_utc(action.updated_at or action.created_at)


def _is_stale_action(action: CareerAction, *, now: datetime) -> bool:
    if action.status not in {"planned", "in_progress"}:
        return False
    if action.due_date is not None and action.due_date < now.date():
        return True
    updated_at = _action_updated_at(action)
    if updated_at is None:
        return False
    return updated_at <= now - timedelta(days=_STALE_ACTION_DAYS)


def _stale_actions(career_plan: CareerPlan | None, *, now: datetime) -> list[CareerAction]:
    if career_plan is None:
        return []
    actions = [action for action in career_plan.actions if _is_stale_action(action, now=now)]
    return sorted(actions, key=lambda action: (action.due_date or date.max, _action_updated_at(action) or now))[:3]


def _event_label(event_type: str) -> str:
    return {
        "profile_completed": "профиль обновлен",
        "analysis_viewed": "анализ открыт",
        "plan_generated": "план сгенерирован",
        "action_created": "действие добавлено",
        "action_completed": "действие завершено",
        "vacancy_saved": "вакансия сохранена",
        "application_outcome": "статус отклика обновлен",
        "weekly_return": "возврат за неделю",
        "digest_engagement": "взаимодействие с дайджестом",
    }.get(event_type, event_type)


def _outcome_label(status: str) -> str:
    return {
        "saved": "сохранено",
        "applied": "отклик",
        "interview": "интервью",
        "offer": "оффер",
        "rejected": "отказ",
        "withdrawn": "отозвано",
    }.get(status, status)


def _outcome_text(event: ApplicationOutcomeEvent) -> str:
    title = event.vacancy_title or event.hh_vacancy_id or "вакансия"
    return f"{title} — {_outcome_label(event.status)}"


def _plan_refresh_suggestions(
    analysis: PersonaAnalysisResponse,
    career_plan: CareerPlan | None,
    stale_actions: list[CareerAction],
) -> list[str]:
    if career_plan is None or not career_plan.actions:
        return ["Сформировать план действий из текущего skill gap."]

    active_generated_skills = {
        (action.skill_name or "").strip().lower()
        for action in career_plan.actions
        if action.recommendation_source == "skill_gap" and action.status not in {"done", "skipped"}
    }
    missing_skills = [
        skill for skill in analysis.recommended_skills[:5] if skill.strip().lower() not in active_generated_skills
    ]
    suggestions: list[str] = []
    if missing_skills:
        suggestions.append(f"Добавить в план навыки: {', '.join(missing_skills[:3])}.")
    if stale_actions:
        suggestions.append("Обновить сроки или статус зависших действий.")
    if not suggestions:
        suggestions.append("План синхронизирован с текущими рекомендациями.")
    return suggestions


def _matches_value(frame: pd.DataFrame, column: str, value: str | None) -> pd.Series:
    if not value or column not in frame.columns:
        return pd.Series(True, index=frame.index)
    return (frame[column].astype("string").str.casefold() == value.casefold()).fillna(False)


def _vacancy_title(row: pd.Series) -> str | None:
    for column in ("title", "name", "vacancy_title"):
        value = row.get(column)
        if value is not None and not pd.isna(value):
            return str(value)
    return None


def _vacancy_url(row: pd.Series) -> str | None:
    for column in ("vacancy_url", "hh_url", "url"):
        value = row.get(column)
        if value is not None and not pd.isna(value):
            return str(value)
    return None


def _find_vacancy_matches(
    datastore: DataStore,
    profile: UserProfile,
    *,
    since: datetime | None,
    limit: int = 3,
) -> list[DigestVacancyMatch]:
    try:
        frame = datastore.get_features_df()
    except Exception:  # noqa: BLE001
        return []
    if frame.empty:
        return []

    filtered = frame.copy()
    mask = pd.Series(True, index=filtered.index)
    mask &= _matches_value(filtered, "primary_role", profile.target_role)
    mask &= _matches_value(filtered, "grade_final", profile.target_grade)
    mask &= _matches_value(filtered, "city_tier", profile.target_city_tier)
    mask &= _matches_value(filtered, "work_mode", profile.target_work_mode)
    mask &= _matches_value(filtered, "domain", profile.target_domain)
    mask &= _matches_value(filtered, "country", profile.target_country)
    mask &= _matches_value(filtered, "region", profile.target_region)
    mask &= _matches_value(filtered, "city_normalized", profile.target_city)
    mask &= _matches_value(filtered, "geo_scope", profile.target_geo_scope)
    filtered = filtered[mask].copy()

    published = None
    if "published_at" in filtered.columns:
        published = pd.to_datetime(filtered["published_at"], errors="coerce", utc=True)
        if since is not None:
            since_utc = _ensure_aware_utc(since)
            if since_utc is not None:
                filtered = filtered[published >= since_utc].copy()
                published = published.loc[filtered.index]

    if filtered.empty:
        return []
    if published is not None:
        filtered = filtered.assign(_published_at=published).sort_values("_published_at", ascending=False)

    matches: list[DigestVacancyMatch] = []
    for _, row in filtered.head(limit).iterrows():
        title = _vacancy_title(row)
        if not title:
            continue
        published_at = _ensure_aware_utc(row.get("_published_at")) if "_published_at" in row else None
        matches.append(DigestVacancyMatch(title=title, url=_vacancy_url(row), published_at=published_at))
    return matches


def build_persona_profile(profile: UserProfile, user: User) -> PersonaProfile:
    constraints: dict[str, str] = {}
    if profile.target_domain:
        constraints["domain"] = profile.target_domain

    return PersonaProfile(
        name=user.username or f"user-{user.telegram_user_id}",
        description="Weekly digest persona",
        current_skills=profile.current_skills,
        target_role=profile.target_role or "",
        target_grade=profile.target_grade,
        target_city_tier=profile.target_city_tier,
        target_country=profile.target_country,
        target_region=profile.target_region,
        target_city=profile.target_city,
        target_geo_scope=profile.target_geo_scope,
        target_work_mode=profile.target_work_mode,
        skill_whitelist=None,
        constraints=constraints,
        goals=[],
        limitations=[],
    )


def _render_digest_html(
    user: User,
    profile: UserProfile,
    summary: SegmentSummary,
    analysis: PersonaAnalysisResponse,
    career_plan: CareerPlan | None = None,
    activity: DigestActivityContext | None = None,
    vacancy_matches: list[DigestVacancyMatch] | None = None,
) -> str:
    role = escape(profile.target_role or "не задано")
    grade = escape(profile.target_grade or "не задано")
    city = escape(profile.target_city or profile.target_city_tier or "не задано")
    geo_scope = escape(profile.target_geo_scope or "не задано")
    work_mode = escape(profile.target_work_mode or "не задано")
    domain = escape(profile.target_domain or "не задано")

    salary_line = (
        f"Зарплаты (25/50/75): {_format_salary(summary.salary_q25)} / "
        f"{_format_salary(summary.salary_median)} / {_format_salary(summary.salary_q75)}"
    )

    recommended = analysis.recommended_skills[:7]
    recommended_lines = _bullet_list(recommended, "рекомендаций нет")

    demand_entries = analysis.top_skill_demand[:5]
    demand_lines = _bullet_list(
        (f"{entry.skill_name} — {round(entry.market_share * 100)}%" for entry in demand_entries),
        "нет данных",
    )

    warnings = list(summary.warnings or []) + list(analysis.warnings or [])
    warning_lines = _bullet_list(warnings, "нет предупреждений") if warnings else []
    active_actions: list[CareerAction] = []
    completed_actions = 0
    total_actions = 0
    now = datetime.now(timezone.utc)
    if career_plan is not None:
        total_actions = len(career_plan.actions)
        completed_actions = sum(1 for action in career_plan.actions if action.status == "done")
        active_actions = [action for action in career_plan.actions if action.status not in {"done", "skipped"}][:3]
    career_plan_lines = _bullet_list(
        (_career_action_text(action) for action in active_actions),
        "нет активных действий",
    )
    stale_actions = _stale_actions(career_plan, now=now)
    stale_action_lines = _bullet_list(
        (_career_action_text(action) for action in stale_actions),
        "зависших действий нет",
    )
    activity = activity or DigestActivityContext()
    event_lines = _bullet_list(
        (f"{_event_label(event_type)}: {count}" for event_type, count in sorted(activity.event_counts.items())),
        "новых событий нет",
    )
    outcome_lines = _bullet_list((_outcome_text(event) for event in activity.outcome_events[:3]), "новых откликов нет")
    vacancy_matches = vacancy_matches or []
    vacancy_lines = _bullet_list((match.title for match in vacancy_matches[:3]), "новых совпадений нет")
    refresh_lines = _bullet_list(_plan_refresh_suggestions(analysis, career_plan, stale_actions))

    lines = [
        "<b>Skillra Weekly Digest</b>",
        (
            "Сегмент: роль — <b>"
            f"{role}</b>; грейд — {grade}; город — {city}; "
            f"рынок — {geo_scope}; формат — {work_mode}; домен — {domain}"
        ),
        "",
        f"Вакансии: {summary.vacancy_count}",
        salary_line,
        f"Удалёнка: {_format_share(summary.remote_share)}",
        f"Junior-friendly: {_format_share(summary.junior_friendly_share)}",
        "",
        "Рекомендуемые навыки:",
        *recommended_lines,
        "",
        "Топ спроса навыков:",
        *demand_lines,
        "",
        "Изменения с прошлого дайджеста:",
        *event_lines,
        "",
        "Отклики:",
        *outcome_lines,
        "",
        "Новые вакансии по профилю:",
        *vacancy_lines,
    ]

    if career_plan is not None:
        lines.extend(
            [
                "",
                "Карьерный план:",
                f"Прогресс: {completed_actions}/{total_actions}",
                "Следующие действия:",
                *career_plan_lines,
                "Зависшие действия:",
                *stale_action_lines,
                "Обновить план:",
                *refresh_lines,
            ]
        )
    else:
        lines.extend(["", "Обновить план:", *refresh_lines])

    if warning_lines:
        lines.extend(["", "Warnings:", *warning_lines])

    return "\n".join(lines)


async def _segment_summary(datastore: DataStore, filters: SegmentFilters) -> SegmentSummary | JSONResponse:
    return await compute_segment_summary(datastore, filters)


async def _persona_analysis(
    datastore: DataStore, persona_profile: PersonaProfile
) -> PersonaAnalysisResponse | JSONResponse:
    return await compute_persona_analysis(datastore, persona_profile)


async def build_digest_preview(
    user: User,
    profile: UserProfile,
    datastore: DataStore,
    career_plan: CareerPlan | None = None,
    activity: DigestActivityContext | None = None,
) -> DigestPreviewResponse:
    """Build digest preview by running segment and persona analysis in parallel.

    Uses :func:`asyncio.gather` for concurrent execution and :func:`asyncio.wait_for`
    for a hard timeout. Returns :func:`unavailable_digest_response` on timeout or data errors
    instead of propagating exceptions (see ADR-002 / GAP-12).
    """

    filters = SegmentFilters(
        role=profile.target_role,
        grade=profile.target_grade,
        city_tier=profile.target_city_tier,
        country=profile.target_country,
        region=profile.target_region,
        city=profile.target_city,
        geo_scope=profile.target_geo_scope,
        work_mode=profile.target_work_mode,
        domain=profile.target_domain,
    )
    persona_profile = build_persona_profile(profile, user)

    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                _segment_summary(datastore, filters),
                _persona_analysis(datastore, persona_profile),
            ),
            timeout=_DIGEST_BUILD_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Digest build timed out after %.1fs for user %s",
            _DIGEST_BUILD_TIMEOUT_SECONDS,
            user.telegram_user_id,
        )
        return DigestPreviewResponse(
            **dataset_trust_payload(datastore),
            format="HTML",
            text="<b>Skillra Weekly Digest</b>\nВремя ожидания ответа истекло. Попробуйте позже.",
        )

    summary, analysis = results

    # Routers may return JSONResponse on data unavailability; treat as degraded state.
    if not isinstance(summary, SegmentSummary) or not isinstance(analysis, PersonaAnalysisResponse):
        logger.warning(
            "Digest data unavailable for user %s: summary=%s analysis=%s",
            user.telegram_user_id,
            type(summary).__name__,
            type(analysis).__name__,
        )
        return unavailable_digest_response()

    vacancy_matches = _find_vacancy_matches(datastore, profile, since=activity.last_sent_at if activity else None)
    summary = summary.model_copy(
        update=dataset_trust_payload(
            datastore,
            sample_size=summary.sample_size or summary.vacancy_count,
            confidence=summary.confidence,
        )
    )
    text = _render_digest_html(user, profile, summary, analysis, career_plan, activity, vacancy_matches)
    return DigestPreviewResponse(
        **dataset_trust_payload(
            datastore,
            sample_size=summary.sample_size or summary.vacancy_count,
            confidence=summary.confidence,
        ),
        format="HTML",
        text=text,
    )


def unavailable_digest_response() -> DigestPreviewResponse:
    return DigestPreviewResponse(format="HTML", text="<b>Skillra Weekly Digest</b>\nДанные не загружены")
