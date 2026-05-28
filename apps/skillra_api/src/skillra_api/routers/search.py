"""MeiliSearch-powered search endpoints (Sprint-008 TASK-04)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from skillra_api.config import Settings
from skillra_api.datastore import DataStore, DataUnavailableError
from skillra_api.db.models import CareerPlan, IndexerRun, User, VacancySnapshot
from skillra_api.deps import get_datastore_dependency, get_settings_dependency
from skillra_api.deps.auth import require_user_or_service_token
from skillra_api.schemas import SkillSearchResponse, VacancySearchResponse, VacancySearchResult
from skillra_api.services.product_events import build_product_event, normalize_surface
from skillra_api.services.search import SearchService, get_search_client
from skillra_api.services.trust import dataset_trust_payload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanActionMatchContext:
    """Small detached representation of a plan action used for vacancy explanations."""

    id: int
    title: str
    skill_name: str | None
    status: str
    action_type: str


@dataclass(frozen=True)
class VacancyMatchContext:
    """Detached user/profile context for explainable vacancy matching."""

    target_role: str | None = None
    target_grade: str | None = None
    target_country: str | None = None
    target_region: str | None = None
    target_city: str | None = None
    target_geo_scope: str | None = None
    target_work_mode: str | None = None
    target_domain: str | None = None
    current_skills: tuple[str, ...] = ()
    open_actions: tuple[PlanActionMatchContext, ...] = ()
    user_id: int | None = None


router = APIRouter(
    prefix="/v1/search",
    tags=["search"],
    dependencies=[Depends(require_user_or_service_token)],
)


async def _get_search_service(settings: Settings = Depends(get_settings_dependency)) -> SearchService | None:
    """Return SearchService or None if MeiliSearch SDK/client is unavailable."""
    try:
        client = await get_search_client(settings)
        return SearchService(client=client) if client is not None else None
    except Exception as exc:  # pragma: no cover
        logger.warning("MeiliSearch client unavailable: %s", exc)
        return None


def _vacancy_result(snapshot: VacancySnapshot) -> VacancySearchResult:
    return VacancySearchResult(
        hh_vacancy_id=snapshot.hh_vacancy_id,
        title=snapshot.title,
        primary_role=snapshot.primary_role,
        grade=snapshot.grade,
        city=snapshot.city,
        city_tier=snapshot.city_tier,
        country=snapshot.country,
        region=snapshot.region,
        city_normalized=snapshot.city_normalized,
        geo_scope=snapshot.geo_scope,
        salary_from=snapshot.salary_from,
        salary_to=snapshot.salary_to,
        skills=snapshot.skills,
        url=snapshot.url,
        hh_url=snapshot.hh_url or snapshot.url,
        published_at=snapshot.published_at,
        dataset_run_id=snapshot.dataset_run_id,
    )


def _dataset_run_id(datastore: DataStore) -> str | None:
    meta = datastore.get_dataset_meta() or {}
    run_id = meta.get("run_id")
    return str(run_id) if run_id else None


def _dataset_run_id_from_indexer_source(source: str | None) -> str | None:
    if not source or ":" not in source:
        return None
    prefix, run_id = source.split(":", 1)
    if prefix in {"reload", "manual", "background"} and run_id:
        return run_id
    return None


def _resolve_match_telegram_user_id(request: Request, telegram_user_id: int | None) -> int | None:
    authenticated_user_id = getattr(request.state, "telegram_user_id", None)
    if telegram_user_id is None:
        return int(authenticated_user_id) if authenticated_user_id is not None else None
    if authenticated_user_id is not None and int(authenticated_user_id) != telegram_user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "USER_SCOPE_FORBIDDEN",
                "message": "User API key cannot personalize search for another Telegram user.",
                "details": {"telegram_user_id": telegram_user_id},
            },
        )
    return telegram_user_id


async def _load_match_context(request: Request, telegram_user_id: int | None) -> VacancyMatchContext:
    if telegram_user_id is None:
        return VacancyMatchContext()

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return VacancyMatchContext()

    async with session_maker() as session:
        user = await session.scalar(
            select(User)
            .options(
                selectinload(User.profile),
                selectinload(User.career_plan).selectinload(CareerPlan.actions),
            )
            .where(User.telegram_user_id == telegram_user_id)
        )

    if user is None:
        return VacancyMatchContext()

    profile = user.profile
    plan = user.career_plan
    open_actions: list[PlanActionMatchContext] = []
    if plan is not None:
        open_actions = [
            PlanActionMatchContext(
                id=action.id,
                title=action.title,
                skill_name=action.skill_name,
                status=action.status,
                action_type=action.action_type,
            )
            for action in plan.actions
            if action.status not in {"done", "skipped"}
        ]

    if profile is None:
        return VacancyMatchContext(open_actions=tuple(open_actions), user_id=user.id)

    return VacancyMatchContext(
        user_id=user.id,
        target_role=profile.target_role,
        target_grade=profile.target_grade,
        target_country=profile.target_country,
        target_region=profile.target_region,
        target_city=profile.target_city,
        target_geo_scope=profile.target_geo_scope,
        target_work_mode=profile.target_work_mode,
        target_domain=profile.target_domain,
        current_skills=tuple(profile.current_skills or ()),
        open_actions=tuple(open_actions),
    )


def _profile_dimension_warnings(context: VacancyMatchContext) -> list[str]:
    ignored: list[str] = []
    if context.target_work_mode:
        ignored.append("формат работы")
    if context.target_domain:
        ignored.append("домен")
    if not ignored:
        return []
    return [
        "Поиск вакансий пока не использует "
        + ", ".join(ignored)
        + ": в текущем индексе по этим измерениям недостаточно надёжных данных."
    ]


def _search_state(
    *,
    index_status: str | None,
    used_fallback: bool,
    warnings: list[str],
) -> tuple[str, str | None]:
    if used_fallback:
        return "fallback", "MeiliSearch недоступен, результаты возвращены из базы вакансий."
    if index_status in {None, "not_configured"}:
        return "unavailable", "Статус поискового индекса недоступен."
    if index_status != "success":
        return "degraded", f"Статус поискового индекса: {index_status}."
    if warnings:
        return "degraded", warnings[0]
    return "ready", None


def _event_source(value: str | None, *, default: str = "api") -> str:
    return normalize_surface(value, default=default)


def _trust_tier(*, search_state: str, confidence: str | None, freshness: str | None) -> str:
    if search_state != "ready":
        return "degraded_search"
    if freshness == "stale":
        return "stale_data"
    if confidence in {"low", "medium"}:
        return "limited_sample"
    if confidence == "high":
        return "trusted"
    return "unknown"


def _active_filter_names(filters: dict[str, str | None]) -> list[str]:
    return sorted(key for key, value in filters.items() if value)


async def _record_search_events(
    request: Request,
    *,
    context: VacancyMatchContext,
    source: str | None,
    query: str,
    result_count: int,
    search_state: str,
    index_status: str | None,
    dataset_run_id: str | None,
    confidence: str | None,
    freshness: str | None,
    filters: dict[str, str | None],
) -> None:
    if context.user_id is None:
        return

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return

    event_source = _event_source(source)
    payload = {
        "query_length": len(query),
        "result_count": result_count,
        "search_state": search_state,
        "index_status": index_status,
        "dataset_run_id": dataset_run_id,
        "confidence": confidence,
        "freshness": freshness,
        "trust_tier": _trust_tier(search_state=search_state, confidence=confidence, freshness=freshness),
        "filters": _active_filter_names(filters),
    }
    now = datetime.now(timezone.utc)
    event_types = ["vacancy_search_performed"]
    if result_count > 0:
        event_types.append("vacancy_match_explained")
    if search_state != "ready":
        event_types.append("search_degraded_warning_shown")

    async with session_maker() as session:
        for event_type in event_types:
            session.add(
                build_product_event(
                    user_id=context.user_id,
                    event_name=event_type,
                    surface=event_source,
                    entity_type="vacancy_search",
                    entity_id=None,
                    metadata=payload,
                    occurred_at=now,
                )
            )
        await session.commit()


def _norm(value: object) -> str:
    return str(value or "").strip().casefold()


def _matches(value: object, target: object) -> bool:
    return bool(_norm(value) and _norm(value) == _norm(target))


def _skill_map(skills: list[str] | tuple[str, ...]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for skill in skills:
        normalized = _norm(skill)
        if normalized and normalized not in mapped:
            mapped[normalized] = str(skill)
    return mapped


def _score_level(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _plan_relevance(
    result: VacancySearchResult,
    *,
    context: VacancyMatchContext,
    vacancy_skill_map: dict[str, str],
    matched_skills: list[str],
    missing_skills: list[str],
) -> str | None:
    for action in context.open_actions:
        skill_name = _norm(action.skill_name)
        if skill_name and skill_name in vacancy_skill_map:
            return f"Связана с действием плана «{action.title}» по навыку {vacancy_skill_map[skill_name]}."

    if matched_skills or missing_skills:
        first_action = next((action for action in context.open_actions if action.action_type != "saved_vacancy"), None)
        if first_action is not None:
            return f"Можно использовать как практическую проверку действия плана «{first_action.title}»."

    if result.hh_vacancy_id and any(
        action.action_type == "saved_vacancy" and _norm(action.title) == _norm(result.title)
        for action in context.open_actions
    ):
        return "Вакансия уже связана с карьерным планом."

    return None


def _enrich_vacancy_result(
    result: VacancySearchResult,
    *,
    context: VacancyMatchContext,
    role: str | None,
    grade: str | None,
    country: str | None,
    region: str | None,
    city: str | None,
    geo_scope: str | None,
    skill: str | None,
) -> VacancySearchResult:
    target_role = context.target_role or role
    target_grade = context.target_grade or grade
    target_country = context.target_country or country
    target_region = context.target_region or region
    target_city = context.target_city or city
    target_geo_scope = context.target_geo_scope or geo_scope

    vacancy_skills = _skill_map(result.skills)
    profile_skills = _skill_map(context.current_skills)
    explicit_skill = _norm(skill)
    matched_skill_keys = set(vacancy_skills).intersection(profile_skills)
    if explicit_skill and explicit_skill in vacancy_skills:
        matched_skill_keys.add(explicit_skill)
    matched_skills = [vacancy_skills[key] for key in sorted(matched_skill_keys)][:8]
    missing_skills = (
        [original for key, original in vacancy_skills.items() if key not in profile_skills][:8]
        if profile_skills
        else []
    )

    fit_parts: list[str] = []
    gap_parts: list[str] = []
    score: int | None = None

    has_match_signal = any(
        [
            target_role,
            target_grade,
            target_country,
            target_region,
            target_city,
            target_geo_scope,
            profile_skills,
            explicit_skill,
        ]
    )
    if has_match_signal:
        score = 20

    if target_role:
        if _matches(result.primary_role, target_role):
            fit_parts.append(f"роль совпадает с профилем: {result.primary_role}")
            score = (score or 0) + 20
        else:
            gap_parts.append(f"роль отличается от цели: {result.primary_role or 'не определена'}")
    if target_grade:
        if _matches(result.grade, target_grade):
            fit_parts.append(f"грейд совпадает: {result.grade}")
            score = (score or 0) + 15
        else:
            gap_parts.append(f"грейд отличается от цели: {result.grade or 'не определён'}")
    if target_country and _matches(result.country, target_country):
        fit_parts.append(f"страна совпадает: {result.country}")
        score = (score or 0) + 5
    if target_region and _matches(result.region, target_region):
        fit_parts.append(f"регион совпадает: {result.region}")
        score = (score or 0) + 5
    if target_city and (_matches(result.city_normalized, target_city) or _matches(result.city, target_city)):
        fit_parts.append(f"город совпадает: {result.city_normalized or result.city}")
        score = (score or 0) + 5
    if target_geo_scope and _matches(result.geo_scope, target_geo_scope):
        fit_parts.append(f"рынок совпадает: {result.geo_scope}")
        score = (score or 0) + 5

    if vacancy_skills and profile_skills:
        overlap_ratio = len(matched_skill_keys) / max(len(vacancy_skills), 1)
        score = (score or 0) + round(overlap_ratio * 35)
    elif explicit_skill and explicit_skill in vacancy_skills:
        score = (score or 0) + 25

    if matched_skills:
        fit_parts.append("совпавшие навыки: " + ", ".join(matched_skills[:5]))
    if missing_skills:
        gap_parts.append("нужно подтянуть: " + ", ".join(missing_skills[:5]))
    elif vacancy_skills and not profile_skills:
        gap_parts.append("навыки профиля не заполнены, точный skill-gap не рассчитан")

    plan_relevance = _plan_relevance(
        result,
        context=context,
        vacancy_skill_map=vacancy_skills,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
    )
    if plan_relevance:
        score = min((score or 0) + 10, 100)

    result.fit_reason = (
        "; ".join(fit_parts) if fit_parts else "Найдена по запросу; для точного матчинга заполните профиль."
    )
    result.gap_reason = "; ".join(gap_parts) if gap_parts else None
    result.plan_relevance = plan_relevance
    result.matched_skills = matched_skills
    result.missing_skills = missing_skills
    result.match_score = min(score, 100) if score is not None else None
    result.match_level = _score_level(result.match_score)
    return result


async def _search_trust_context(
    request: Request,
    datastore: DataStore,
) -> tuple[str | None, str | None, str | None, list[str]]:
    dataset_run_id = _dataset_run_id(datastore)
    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return (
            dataset_run_id,
            "not_configured",
            None,
            ["Search index status is unavailable: database is not configured."],
        )

    async with session_maker() as session:
        run = await session.scalar(select(IndexerRun).order_by(IndexerRun.started_at.desc(), IndexerRun.id.desc()))

    if run is None:
        return dataset_run_id, "idle", None, ["Search index has not been built yet."]

    index_dataset_run_id = run.dataset_run_id or _dataset_run_id_from_indexer_source(run.source)
    warnings: list[str] = []
    if run.status != "success":
        warnings.append(f"Search index status is {run.status}. Results may be incomplete.")
    if dataset_run_id and index_dataset_run_id and dataset_run_id != index_dataset_run_id:
        warnings.append(
            f"Search index dataset run {index_dataset_run_id} differs from API dataset run {dataset_run_id}."
        )
    elif dataset_run_id and not index_dataset_run_id:
        warnings.append("Search index dataset version is unknown.")
    return dataset_run_id, run.status, index_dataset_run_id, warnings


async def _search_vacancies_db_fallback(
    request: Request,
    q: str,
    *,
    match_context: VacancyMatchContext,
    source: str | None,
    role: str | None,
    grade: str | None,
    country: str | None,
    region: str | None,
    city: str | None,
    geo_scope: str | None,
    skill: str | None,
    limit: int,
    offset: int,
    dataset_run_id: str | None,
    index_status: str | None,
    index_dataset_run_id: str | None,
    warnings: list[str],
    trust: dict,
) -> VacancySearchResponse:
    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        search_state, degraded_reason = _search_state(
            index_status=index_status,
            used_fallback=True,
            warnings=warnings,
        )
        confidence = _search_confidence(0)
        await _record_search_events(
            request,
            context=match_context,
            source=source,
            query=q,
            result_count=0,
            search_state=search_state,
            index_status=index_status,
            dataset_run_id=dataset_run_id,
            confidence=confidence,
            freshness=trust.get("freshness"),
            filters={
                "role": role,
                "grade": grade,
                "country": country,
                "region": region,
                "city": city,
                "geo_scope": geo_scope,
                "skill": skill,
            },
        )
        return VacancySearchResponse(
            **{**trust, "sample_size": 0, "confidence": confidence},
            results=[],
            total=0,
            query=q,
            index_status=index_status,
            index_dataset_run_id=index_dataset_run_id,
            search_state=search_state,
            degraded_reason=degraded_reason,
            warnings=warnings,
        )

    query_like = f"%{q}%"
    stmt = select(VacancySnapshot).where(
        or_(
            VacancySnapshot.title.ilike(query_like),
            VacancySnapshot.description_snippet.ilike(query_like),
        )
    )
    if role:
        stmt = stmt.where(VacancySnapshot.primary_role == role)
    if grade:
        stmt = stmt.where(VacancySnapshot.grade == grade)
    if country:
        stmt = stmt.where(VacancySnapshot.country == country)
    if region:
        stmt = stmt.where(VacancySnapshot.region == region)
    if city:
        stmt = stmt.where(VacancySnapshot.city_normalized == city)
    if geo_scope:
        stmt = stmt.where(VacancySnapshot.geo_scope == geo_scope)
    if skill:
        stmt = stmt.where(VacancySnapshot.skills.contains([skill]))

    async with session_maker() as session:
        rows = (await session.scalars(stmt.offset(offset).limit(limit))).all()

    fallback_warnings = [*warnings]
    fallback_warnings.append("MeiliSearch is unavailable; returned DB fallback results.")
    search_state, degraded_reason = _search_state(
        index_status=index_status,
        used_fallback=True,
        warnings=fallback_warnings,
    )
    confidence = _search_confidence(len(rows))
    await _record_search_events(
        request,
        context=match_context,
        source=source,
        query=q,
        result_count=len(rows),
        search_state=search_state,
        index_status=index_status,
        dataset_run_id=dataset_run_id,
        confidence=confidence,
        freshness=trust.get("freshness"),
        filters={
            "role": role,
            "grade": grade,
            "country": country,
            "region": region,
            "city": city,
            "geo_scope": geo_scope,
            "skill": skill,
        },
    )
    return VacancySearchResponse(
        **{**trust, "sample_size": len(rows), "confidence": confidence},
        results=[
            _enrich_vacancy_result(
                _vacancy_result(row),
                context=match_context,
                role=role,
                grade=grade,
                country=country,
                region=region,
                city=city,
                geo_scope=geo_scope,
                skill=skill,
            )
            for row in rows
        ],
        total=len(rows),
        query=q,
        index_status=index_status,
        index_dataset_run_id=index_dataset_run_id,
        search_state=search_state,
        degraded_reason=degraded_reason,
        warnings=fallback_warnings,
    )


@router.get("/vacancies", response_model=VacancySearchResponse, response_class=JSONResponse)
async def search_vacancies(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200, description="Full-text search query"),
    role: str | None = Query(None, description="Filter by primary role"),
    grade: str | None = Query(None, description="Filter by grade"),
    country: str | None = Query(None, description="Filter by country"),
    region: str | None = Query(None, description="Filter by region"),
    city: str | None = Query(None, description="Filter by normalized city"),
    geo_scope: str | None = Query(None, description="Filter by market geography scope"),
    skill: str | None = Query(None, description="Filter by required skill"),
    telegram_user_id: int | None = Query(None, description="Optional user id for personalized match explanations"),
    source: str | None = Query("api", description="Product event source"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    search_service: SearchService | None = Depends(_get_search_service),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> VacancySearchResponse:
    """Search vacancies using MeiliSearch full-text index."""

    dataset_run_id, index_status, index_dataset_run_id, warnings = await _search_trust_context(request, datastore)
    resolved_telegram_user_id = _resolve_match_telegram_user_id(request, telegram_user_id)
    match_context = await _load_match_context(request, resolved_telegram_user_id)
    warnings = [*warnings, *_profile_dimension_warnings(match_context)]
    trust = dataset_trust_payload(datastore)

    if search_service is None:
        return await _search_vacancies_db_fallback(
            request,
            q,
            match_context=match_context,
            source=source,
            role=role,
            grade=grade,
            country=country,
            region=region,
            city=city,
            geo_scope=geo_scope,
            skill=skill,
            limit=limit,
            offset=offset,
            dataset_run_id=dataset_run_id,
            index_status=index_status,
            index_dataset_run_id=index_dataset_run_id,
            warnings=warnings,
            trust=trust,
        )

    try:
        search_result = await search_service.search_vacancies(
            q,
            limit=limit,
            offset=offset,
            role=role,
            grade=grade,
            country=country,
            region=region,
            city=city,
            geo_scope=geo_scope,
            skill=skill,
        )

        results = [
            _enrich_vacancy_result(
                VacancySearchResult(
                    hh_vacancy_id=hit.get("hh_vacancy_id", ""),
                    title=hit.get("title", ""),
                    primary_role=hit.get("primary_role"),
                    grade=hit.get("grade"),
                    city=hit.get("city"),
                    city_tier=hit.get("city_tier"),
                    country=hit.get("country"),
                    region=hit.get("region"),
                    city_normalized=hit.get("city_normalized"),
                    geo_scope=hit.get("geo_scope"),
                    salary_from=hit.get("salary_from"),
                    salary_to=hit.get("salary_to"),
                    skills=hit.get("skills", []),
                    url=hit.get("url"),
                    hh_url=hit.get("hh_url") or hit.get("url"),
                    published_at=hit.get("published_at"),
                    dataset_run_id=hit.get("dataset_run_id"),
                ),
                context=match_context,
                role=role,
                grade=grade,
                country=country,
                region=region,
                city=city,
                geo_scope=geo_scope,
                skill=skill,
            )
            for hit in (search_result.hits or [])
        ]

        total = search_result.estimated_total_hits or len(results)
        search_state, degraded_reason = _search_state(
            index_status=index_status,
            used_fallback=False,
            warnings=warnings,
        )
        confidence = _search_confidence(total)
        await _record_search_events(
            request,
            context=match_context,
            source=source,
            query=q,
            result_count=total,
            search_state=search_state,
            index_status=index_status,
            dataset_run_id=dataset_run_id,
            confidence=confidence,
            freshness=trust.get("freshness"),
            filters={
                "role": role,
                "grade": grade,
                "country": country,
                "region": region,
                "city": city,
                "geo_scope": geo_scope,
                "skill": skill,
            },
        )
        return VacancySearchResponse(
            **{**trust, "sample_size": total, "confidence": confidence},
            results=results,
            total=total,
            query=q,
            index_status=index_status,
            index_dataset_run_id=index_dataset_run_id,
            search_state=search_state,
            degraded_reason=degraded_reason,
            warnings=warnings,
        )

    except Exception as exc:  # pragma: no cover
        logger.warning("MeiliSearch search error: %s", exc)
        return await _search_vacancies_db_fallback(
            request,
            q,
            match_context=match_context,
            source=source,
            role=role,
            grade=grade,
            country=country,
            region=region,
            city=city,
            geo_scope=geo_scope,
            skill=skill,
            limit=limit,
            offset=offset,
            dataset_run_id=dataset_run_id,
            index_status=index_status,
            index_dataset_run_id=index_dataset_run_id,
            warnings=warnings,
            trust=trust,
        )


@router.get("/skills", response_model=SkillSearchResponse, response_class=JSONResponse)
async def search_skills(
    q: str = Query(..., min_length=1, max_length=100, description="Skill search query"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
    search_service: SearchService | None = Depends(_get_search_service),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> SkillSearchResponse:
    """Search skills using MeiliSearch index with DataStore fallback."""

    if search_service is not None:
        try:
            result = await search_service.search_skills(q, limit=limit)
            skills = [hit.get("name", "") for hit in (result.hits or []) if hit.get("name")]
            if skills:
                return SkillSearchResponse(skills=skills, total=result.estimated_total_hits or len(skills))
            logger.info("MeiliSearch skill index returned no hits; falling back to DataStore")
        except Exception as exc:  # pragma: no cover
            logger.warning("MeiliSearch skill search error: %s", exc)

    if not datastore.is_ready:
        return SkillSearchResponse(skills=[], total=0)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return SkillSearchResponse(skills=[], total=0)

    all_skills = sorted(
        {
            col.removeprefix("skill_").removeprefix("has_")
            for col in features_df.columns
            if col.startswith("skill_") or col.startswith("has_")
        }
    )
    q_lower = q.lower()
    skills = [skill for skill in all_skills if q_lower in skill.lower()][:limit]
    return SkillSearchResponse(skills=skills, total=len(skills))


def _search_confidence(total: int | None) -> str:
    if not total:
        return "low"
    if total >= 30:
        return "high"
    if total >= 5:
        return "medium"
    return "low"
