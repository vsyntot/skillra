from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from skillra_api.config import Settings
from skillra_api.datastore import DataStore, DataUnavailableError
from skillra_api.db.models import (
    ApplicationOutcomeEvent,
    CareerAction,
    CareerPlan,
    ProductEvent,
    User,
    UserApiKey,
    UserCommercialAccount,
    UserProfile,
    UserResume,
    WeeklySubscription,
)
from skillra_api.deps import get_datastore_dependency, get_db_session, get_settings_dependency
from skillra_api.deps.auth import (
    require_admin_token,
    require_service_or_matching_user,
    require_service_token,
    require_user_or_service_token,
)
from skillra_api.metrics import (
    APPLICATION_OUTCOMES_TOTAL,
    CAREER_ACTIONS_TOTAL,
    EVIDENCE_EXPLAINER_BLOCKED_CLAIMS_TOTAL,
    EVIDENCE_EXPLAINER_LATENCY_SECONDS,
    EVIDENCE_EXPLAINER_REQUESTS_TOTAL,
    PROFILES_TOTAL,
)
from skillra_api.schemas import (
    ApplicationOutcomeIn,
    CareerActionIn,
    CareerActionOut,
    CareerActionPatch,
    CareerPlanGenerateActionsIn,
    CareerPlanIn,
    CareerPlanOut,
    CareerPlanPatch,
    CommercialStateOut,
    EvidenceExplainerOut,
    EvidencePacketOut,
    EvidenceSurface,
    EvidenceTask,
    NextBestActionOut,
    PersonaAnalysisResponse,
    PersonaProfile,
    ProductCohortSummaryOut,
    ProductEventIn,
    ProductEventOut,
    ProductLoopSummaryOut,
    ProfileQualityOut,
    ResumePresignedUrlOut,
    ResumeStatusOut,
    ResumeUploadOut,
    SavedVacancyIn,
    UserApiKeyOut,
    UserApiKeyRevokeOut,
    UserApiKeyStatusOut,
    UserProfileIn,
    UserProfileOut,
    UserSummaryOut,
)
from skillra_api.services.analytics import compute_persona_analysis
from skillra_api.services.commercial import (
    ENTITLEMENT_CAREER_PLAN_GENERATE,
    commercial_state_payload,
    ensure_user_entitlement,
    get_or_create_commercial_account,
)
from skillra_api.services.evidence_explainer import build_deterministic_explainer, build_evidence_packet
from skillra_api.services.product_events import (
    PRODUCT_EVENT_NAMES,
    PRODUCT_EVENT_SURFACES,
    USER_ACTIVATION_EVENT_SURFACES,
    ProductEventValidationError,
    build_product_event,
    normalize_surface,
    record_product_event,
)
from skillra_api.services.responses import invalid_skills_error, profile_not_found_error
from skillra_api.services.resume_parser import parse_pdf_resume
from skillra_api.services.storage_service import StorageNotConfiguredError, StorageService
from skillra_api.services.trust import dataset_trust_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/users", tags=["users"])
auth_router = APIRouter(prefix="/v1/users", tags=["users"])
admin_router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_service_token), Depends(require_admin_token)],
)

PRODUCT_EVENT_LABELS = PRODUCT_EVENT_NAMES
PRODUCT_EVENT_SOURCES = PRODUCT_EVENT_SURFACES
USER_ACTIVATION_EVENT_SOURCES = USER_ACTIVATION_EVENT_SURFACES
CAREER_ACTION_LABELS = {"learning", "application", "portfolio", "networking", "saved_vacancy", "other"}
RECOMMENDATION_SOURCE_LABELS = {"manual", "skill_gap", "search", "digest", "user"}
APPLICATION_OUTCOME_LABELS = {"saved", "applied", "interview", "offer", "rejected", "withdrawn"}
EVIDENCE_EXPLAINER_STATUSES = {
    "answered",
    "fallback",
    "blocked",
    "disabled",
    "not_allowed",
    "profile_missing",
}


def _parse_telegram_user_id_allowlist(value: str | None) -> set[int]:
    ids: set[int] = set()
    if not value:
        return ids
    for raw_item in str(value).replace(";", ",").split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            logger.warning("Ignoring invalid evidence explainer allowlist item", extra={"item": item[:32]})
    return ids


def _evidence_explainer_denial_reason(settings: Settings, telegram_user_id: int) -> str | None:
    if not settings.evidence_explainer_enabled:
        return "disabled"
    allowed_ids = _parse_telegram_user_id_allowlist(settings.evidence_explainer_allowed_telegram_user_ids)
    if settings.runtime_env == "prod":
        if not settings.evidence_explainer_prod_enable_approved:
            return "prod_not_approved"
        if not allowed_ids:
            return "prod_allowlist_required"
    if settings.runtime_env == "staging" and not allowed_ids:
        return "staging_allowlist_required"
    if allowed_ids and telegram_user_id not in allowed_ids:
        return "not_allowed"
    return None


def _record_evidence_explainer_metrics(
    *,
    settings: Settings,
    task: EvidenceTask,
    surface: EvidenceSurface,
    status: str,
    started_at: float,
    blocked_claims: list[str] | None = None,
) -> None:
    bounded_status = status if status in EVIDENCE_EXPLAINER_STATUSES else "blocked"
    labels = {
        "runtime_env": settings.runtime_env,
        "task": str(task),
        "surface": str(surface),
        "status": bounded_status,
    }
    EVIDENCE_EXPLAINER_REQUESTS_TOTAL.labels(**labels).inc()
    EVIDENCE_EXPLAINER_LATENCY_SECONDS.labels(**labels).observe(max(time.perf_counter() - started_at, 0.0))
    for claim in blocked_claims or []:
        EVIDENCE_EXPLAINER_BLOCKED_CLAIMS_TOTAL.labels(
            runtime_env=settings.runtime_env,
            task=str(task),
            claim=str(claim)[:64],
        ).inc()


def _bounded_label(value: str | None, allowed: set[str], default: str = "other") -> str:
    if not value:
        return default
    normalized = str(value).strip().lower()
    return normalized if normalized in allowed else default


def _event_source(value: str | None, *, default: str = "api") -> str:
    return normalize_surface(value, default=default)


def _generate_api_key(telegram_user_id: int) -> tuple[str, str, str]:
    random_part = secrets.token_urlsafe(18)
    plaintext = f"sk_{telegram_user_id}_{random_part}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    key_prefix = plaintext[:8]
    return plaintext, key_hash, key_prefix


def _profile_out(user: User, profile: UserProfile, warnings: list[str] | None = None) -> UserProfileOut:
    return UserProfileOut(
        telegram_user_id=user.telegram_user_id,
        username=user.username,
        target_role=profile.target_role,
        target_grade=profile.target_grade,
        target_city_tier=profile.target_city_tier,
        target_country=profile.target_country,
        target_region=profile.target_region,
        target_city=profile.target_city,
        target_geo_scope=profile.target_geo_scope,
        target_work_mode=profile.target_work_mode,
        target_domain=profile.target_domain,
        current_skills=profile.current_skills,
        warnings=warnings or [],
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _career_action_out(action: CareerAction) -> CareerActionOut:
    return CareerActionOut(
        id=action.id,
        title=action.title,
        description=action.description,
        action_type=action.action_type,
        status=action.status,
        priority=action.priority,
        skill_name=action.skill_name,
        hh_vacancy_id=action.hh_vacancy_id,
        vacancy_title=action.vacancy_title,
        vacancy_url=action.vacancy_url,
        recommendation_source=action.recommendation_source,
        dataset_run_id=action.dataset_run_id,
        reason=action.reason,
        expected_impact=action.expected_impact,
        effort_estimate=action.effort_estimate,
        due_date=action.due_date,
        review_date=action.due_date,
        evidence=action.evidence,
        application_status=action.application_status,
        created_at=action.created_at,
        updated_at=action.updated_at,
        completed_at=action.completed_at,
    )


def _career_plan_out(user: User, plan: CareerPlan) -> CareerPlanOut:
    return CareerPlanOut(
        telegram_user_id=user.telegram_user_id,
        target_role=plan.target_role,
        target_grade=plan.target_grade,
        target_city_tier=plan.target_city_tier,
        target_country=plan.target_country,
        target_region=plan.target_region,
        target_city=plan.target_city,
        target_geo_scope=plan.target_geo_scope,
        target_work_mode=plan.target_work_mode,
        target_domain=plan.target_domain,
        status=plan.status,
        notes=plan.notes,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        actions=[_career_action_out(action) for action in plan.actions],
    )


def _career_plan_not_found(telegram_user_id: int) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error_code": "CAREER_PLAN_NOT_FOUND",
            "message": f"Career plan for telegram_user_id={telegram_user_id} not found.",
            "details": {"telegram_user_id": telegram_user_id},
        },
    )


def _storage_service(request: Request, settings: Settings) -> StorageService:
    service = getattr(request.app.state, "storage_service", None)
    return service if service is not None else StorageService(settings)


def _resume_skills(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(skill) for skill in parsed] if isinstance(parsed, list) else []


async def _read_resume_upload(request: Request, filename: str | None) -> tuple[str, str, bytes]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        try:
            form = await request.form()
        except AssertionError as exc:
            raise HTTPException(status_code=415, detail="python-multipart is required for multipart uploads") from exc
        upload = form.get("file") or form.get("resume")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail="multipart field 'file' is required")
        file_bytes = await upload.read()
        original_filename = getattr(upload, "filename", None) or filename or "resume.pdf"
        upload_content_type = getattr(upload, "content_type", None) or "application/pdf"
        return str(original_filename), str(upload_content_type), file_bytes

    file_bytes = await request.body()
    return filename or "resume.pdf", content_type.split(";", 1)[0] or "application/pdf", file_bytes


async def _get_or_create_user(session: AsyncSession, telegram_user_id: int) -> User:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        user = User(telegram_user_id=telegram_user_id)
        session.add(user)
        await session.flush()
    return user


async def _active_api_key(session: AsyncSession, user_id: int) -> UserApiKey | None:
    return await session.scalar(
        select(UserApiKey)
        .where(UserApiKey.user_id == user_id, UserApiKey.revoked_at.is_(None))
        .order_by(UserApiKey.created_at.desc(), UserApiKey.id.desc())
    )


async def _get_user_with_career_plan(
    session: AsyncSession,
    telegram_user_id: int,
) -> tuple[User | None, CareerPlan | None]:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return None, None
    plan = await session.scalar(
        select(CareerPlan)
        .options(selectinload(CareerPlan.actions))
        .where(CareerPlan.user_id == user.id)
        .order_by(CareerPlan.id.desc())
    )
    return user, plan


async def _get_required_career_plan(
    session: AsyncSession,
    telegram_user_id: int,
) -> tuple[User, CareerPlan] | JSONResponse:
    user, plan = await _get_user_with_career_plan(session, telegram_user_id)
    if user is None or plan is None:
        return _career_plan_not_found(telegram_user_id)
    return user, plan


async def _profile_for_user(session: AsyncSession, user_id: int) -> UserProfile | None:
    return await session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))


def _dataset_run_id(datastore: DataStore) -> str | None:
    meta = datastore.get_dataset_meta() or {}
    run_id = meta.get("run_id")
    return str(run_id) if run_id else None


def _profile_quality(profile: UserProfile | None) -> ProfileQualityOut:
    checks: list[tuple[str, bool]] = [
        ("target_role", bool(profile and profile.target_role)),
        ("target_grade", bool(profile and profile.target_grade)),
        (
            "target_geo",
            bool(
                profile
                and (
                    profile.target_city_tier
                    or profile.target_country
                    or profile.target_region
                    or profile.target_city
                    or profile.target_geo_scope
                )
            ),
        ),
        ("target_work_mode", bool(profile and profile.target_work_mode)),
        ("target_domain", bool(profile and profile.target_domain)),
        ("current_skills", bool(profile and profile.current_skills)),
    ]
    completed_fields = [field for field, is_done in checks if is_done]
    missing_fields = [field for field, is_done in checks if not is_done]
    score = round(len(completed_fields) / len(checks) * 100)
    return ProfileQualityOut(
        score=score,
        is_complete=not missing_fields,
        completed_fields=completed_fields,
        missing_fields=missing_fields,
    )


def _dataset_trust_warning(datastore: DataStore) -> str | None:
    if not datastore.is_ready:
        return "Рыночные данные сейчас обновляются; следующий шаг можно сохранить, но аналитика может быть неполной."

    meta = datastore.get_dataset_meta() or {}
    trust = dataset_trust_payload(datastore)
    quality = meta.get("quality_gates")
    if isinstance(quality, dict) and quality.get("status") not in {None, "passed"}:
        return "Последний датасет не прошел проверку качества, поэтому используем предыдущий опубликованный срез."

    if trust.get("date_semantics_status") not in {None, "passed"}:
        return (
            "У данных есть предупреждение по датам публикации вакансий; "
            "интерпретируйте исторические выводы осторожно."
        )

    if trust.get("freshness") == "stale":
        return "Рыночные данные старше 30 дней; перед важным решением проверьте свежий поиск вакансий."

    return None


def _first_open_action(plan: CareerPlan | None) -> CareerAction | None:
    if plan is None:
        return None
    return next(
        (
            action
            for action in plan.actions
            if action.action_type != "saved_vacancy" and action.status in {"planned", "in_progress"}
        ),
        None,
    )


def _saved_vacancy_action(plan: CareerPlan | None) -> CareerAction | None:
    if plan is None:
        return None
    return next((action for action in plan.actions if action.action_type == "saved_vacancy"), None)


def _next_best_action(
    telegram_user_id: int,
    profile: UserProfile | None,
    plan: CareerPlan | None,
    subscription: WeeklySubscription | None,
    datastore: DataStore,
) -> NextBestActionOut:
    profile_quality = _profile_quality(profile)
    trust_warning = _dataset_trust_warning(datastore)

    if profile is None:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="create_profile",
            action_id="create_profile",
            title="Создать профиль",
            reason="Без цели, уровня, географии и навыков Skillra не сможет сравнить вас с рынком.",
            cta="Заполнить профиль",
            target_surface="web",
            route="/profile",
            command="/profile",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    if not profile_quality.is_complete:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="complete_profile",
            action_id="complete_profile",
            title="Дозаполнить профиль",
            reason="Профиль уже создан, но нескольких полей не хватает для уверенной персонализации.",
            cta="Дозаполнить",
            target_surface="web",
            route="/profile",
            command="/profile",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    if trust_warning and not datastore.is_ready:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="data_unavailable",
            action_id="wait_for_market_data",
            title="Дождаться рыночных данных",
            reason="Профиль готов, но аналитический слой временно не готов к расчету следующего рыночного шага.",
            cta="Проверить статус",
            target_surface="bot",
            route="/",
            command="/status",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    if plan is None:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="create_plan",
            action_id="create_career_plan",
            title="Собрать карьерный план",
            reason="Профиль готов; следующий шаг - превратить разрыв с рынком в конкретный план действий.",
            cta="Собрать план",
            target_surface="web",
            route="/career-plan",
            command="/plan",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    open_action = _first_open_action(plan)
    if open_action is None:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="generate_plan_actions",
            action_id="generate_plan_actions",
            title="Получить действия по skill-gap",
            reason="План есть, но в нем нет открытых действий, привязанных к рыночному разрыву.",
            cta="Сгенерировать действия",
            target_surface="web",
            route="/skill-gap",
            command="/plan_recommend",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    saved_vacancy = _saved_vacancy_action(plan)
    if saved_vacancy is None:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="find_vacancy",
            action_id="find_matching_vacancy",
            title="Найти подходящую вакансию",
            reason=(
                f"В плане уже есть действие: {open_action.title}. "
                "Теперь нужен рыночный пример, к которому его привязать."
            ),
            cta="Искать вакансии",
            target_surface="web",
            route="/search",
            command="/search",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    if saved_vacancy.application_status in {None, "saved"}:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="update_application_outcome",
            action_id=f"update_application_{saved_vacancy.id}",
            title="Обновить статус отклика",
            reason="Вакансия сохранена, но следующий карьерный сигнал появится только после статуса отклика.",
            cta="Обновить статус",
            target_surface="web",
            route="/career-plan",
            command="/plan",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    if subscription is None or not subscription.active:
        return NextBestActionOut(
            telegram_user_id=telegram_user_id,
            state="enable_digest",
            action_id="enable_weekly_digest",
            title="Включить еженедельный дайджест",
            reason="Профиль, план и вакансия уже есть; дайджест поможет не терять новые сигналы рынка.",
            cta="Включить дайджест",
            target_surface="bot",
            route="/subscription",
            command="/subscribe",
            trust_warning=trust_warning,
            profile_quality=profile_quality,
        )

    return NextBestActionOut(
        telegram_user_id=telegram_user_id,
        state="continue_plan",
        action_id=f"continue_action_{open_action.id}",
        title=open_action.title,
        reason="Основной контур запущен; самый полезный следующий шаг - довести открытое действие до результата.",
        cta="Продолжить план",
        target_surface="web",
        route="/career-plan",
        command="/plan",
        trust_warning=trust_warning,
        profile_quality=profile_quality,
    )


def _persona_profile_from_user_profile(user: User, profile: UserProfile) -> PersonaProfile:
    constraints: dict[str, str] = {}
    if profile.target_domain:
        constraints["domain"] = profile.target_domain
    return PersonaProfile(
        name=user.username or f"user-{user.telegram_user_id}",
        description="Career plan generation profile",
        current_skills=profile.current_skills,
        target_role=profile.target_role or "",
        target_grade=profile.target_grade,
        target_city_tier=profile.target_city_tier,
        target_country=profile.target_country,
        target_region=profile.target_region,
        target_city=profile.target_city,
        target_geo_scope=profile.target_geo_scope,
        target_work_mode=profile.target_work_mode,
        constraints=constraints,
    )


def _search_context_from_request(request: Request) -> tuple[str, str | None, str | None, list[str]]:
    meili_status = str(getattr(request.app.state, "meilisearch_status", "not_configured"))
    if meili_status == "ok":
        return "ready", "ok", None, []
    if meili_status == "degraded":
        return (
            "degraded",
            "degraded",
            "MeiliSearch health check is degraded.",
            [
                "meilisearch_degraded",
            ],
        )
    if meili_status == "not_configured":
        return (
            "fallback",
            "not_configured",
            "MeiliSearch is not configured; database fallback may be used.",
            [
                "meilisearch_not_configured",
            ],
        )
    return "unavailable", meili_status, "Vacancy search runtime state is unknown.", ["search_state_unknown"]


async def _build_user_evidence_packet(
    *,
    telegram_user_id: int,
    task: EvidenceTask,
    surface: EvidenceSurface,
    request: Request,
    session: AsyncSession,
    datastore: DataStore,
) -> EvidencePacketOut | JSONResponse:
    user = await session.scalar(
        select(User)
        .options(selectinload(User.profile), selectinload(User.career_plan).selectinload(CareerPlan.actions))
        .where(User.telegram_user_id == telegram_user_id)
    )
    if user is None or user.profile is None:
        return profile_not_found_error(telegram_user_id)

    analysis = await compute_persona_analysis(datastore, _persona_profile_from_user_profile(user, user.profile))
    if not isinstance(analysis, PersonaAnalysisResponse):
        return analysis

    search_state, index_status, degraded_reason, search_warnings = _search_context_from_request(request)
    return build_evidence_packet(
        telegram_user_id=telegram_user_id,
        profile=_profile_out(user, user.profile),
        profile_quality=_profile_quality(user.profile),
        analysis=analysis,
        plan=_career_plan_out(user, user.career_plan) if user.career_plan is not None else None,
        task=task,
        surface=surface,
        search_state=search_state,
        index_status=index_status,
        degraded_reason=degraded_reason,
        search_warnings=search_warnings,
    )


def _product_event(
    user_id: int,
    event_type: str,
    *,
    source: str = "api",
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> ProductEvent:
    return build_product_event(
        user_id=user_id,
        event_name=event_type,
        surface=source,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata=payload,
    )


def _product_event_out(event: ProductEvent) -> ProductEventOut:
    return ProductEventOut(
        id=event.id,
        event_name=event.event_type,
        surface=event.source,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        request_id=event.request_id,
        session_id=event.session_id,
        correlation_id=event.correlation_id,
        metadata=event.payload if isinstance(event.payload, dict) else {},
        occurred_at=event.occurred_at,
    )


def _commercial_state_out(account: UserCommercialAccount) -> CommercialStateOut:
    return CommercialStateOut(**commercial_state_payload(account))


def _available_skills(datastore: DataStore) -> set[str] | None:
    if not datastore.is_ready:
        return None

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return None

    skill_columns = [col for col in features_df.columns if col.startswith("skill_") or col.startswith("has_")]
    return {col.removeprefix("skill_").removeprefix("has_") for col in skill_columns}


def _known_skills(datastore: DataStore) -> list[str]:
    return sorted(_available_skills(datastore) or [])


def _meta_values(datastore: DataStore, column: str) -> list[str] | None:
    if not datastore.is_ready:
        return None

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return None

    if column == "grade":
        column = "grade_final" if "grade_final" in market_view_df.columns else "grade"
    if column not in market_view_df.columns:
        return []

    return sorted({str(value) for value in market_view_df[column].dropna().unique().tolist()})


def _validate_meta_value(value: str | None, allowed: list[str] | None, field: str, warnings: list[str]) -> None:
    if value is None or value == "":
        return
    if allowed is None:
        warnings.append(f"{field} validation skipped: meta values are unavailable.")
        return
    allowed_lower = {item.lower() for item in allowed}
    if value not in allowed and value.lower() not in allowed_lower:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_META_VALUE",
                "message": f"Invalid {field}: '{value}'",
                "details": {"allowed": allowed},
            },
        )


@router.put(
    "/{telegram_user_id}/profile",
    response_model=UserProfileOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def upsert_user_profile(
    telegram_user_id: int,
    payload: UserProfileIn,
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> UserProfileOut | JSONResponse:
    available_skills = _available_skills(datastore)
    warnings: list[str] = []

    _validate_meta_value(payload.target_role, _meta_values(datastore, "primary_role"), "target_role", warnings)
    _validate_meta_value(payload.target_grade, _meta_values(datastore, "grade"), "target_grade", warnings)

    if available_skills is None:
        warnings.append("Skills validation skipped: meta skills are unavailable.")
    else:
        invalid_skills = [skill for skill in payload.current_skills if skill not in available_skills]
        if invalid_skills:
            return invalid_skills_error(invalid_skills)

    profile_created = False
    async with session.begin():
        user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        if not user:
            user = User(telegram_user_id=telegram_user_id, username=payload.username)
            session.add(user)
            await session.flush()
        elif payload.username is not None:
            user.username = payload.username

        profile = await session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
        if not profile:
            profile = UserProfile(
                user_id=user.id,
                target_role=payload.target_role,
                target_grade=payload.target_grade,
                target_city_tier=payload.target_city_tier,
                target_country=payload.target_country,
                target_region=payload.target_region,
                target_city=payload.target_city,
                target_geo_scope=payload.target_geo_scope,
                target_work_mode=payload.target_work_mode,
                target_domain=payload.target_domain,
                current_skills=payload.current_skills,
            )
            session.add(profile)
            profile_created = True
        else:
            profile.target_role = payload.target_role
            profile.target_grade = payload.target_grade
            profile.target_city_tier = payload.target_city_tier
            profile.target_country = payload.target_country
            profile.target_region = payload.target_region
            profile.target_city = payload.target_city
            profile.target_geo_scope = payload.target_geo_scope
            profile.target_work_mode = payload.target_work_mode
            profile.target_domain = payload.target_domain
            profile.current_skills = payload.current_skills
        session.add(
            _product_event(
                user.id,
                "profile_completed",
                source=_event_source(payload.source),
                entity_type="profile",
                payload={
                    "has_target_role": payload.target_role is not None,
                    "has_skills": bool(payload.current_skills),
                },
            )
        )

    await session.refresh(user)
    await session.refresh(profile)
    if profile_created:
        PROFILES_TOTAL.inc()

    return _profile_out(user, profile, warnings)


@router.get(
    "/{telegram_user_id}/profile",
    response_model=UserProfileOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_user_profile(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> UserProfileOut | JSONResponse:
    result = await session.execute(
        select(User, UserProfile)
        .join(UserProfile, User.id == UserProfile.user_id, isouter=True)
        .where(User.telegram_user_id == telegram_user_id)
    )
    row = result.first()
    if not row or row[1] is None:
        return profile_not_found_error(telegram_user_id)

    user, profile = row
    return _profile_out(user, profile)


@router.get(
    "/{telegram_user_id}/next-best-action",
    response_model=NextBestActionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_next_best_action(
    telegram_user_id: int,
    source: str | None = Query(None, max_length=32),
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> NextBestActionOut:
    """Return the single shared activation recommendation for web and Telegram."""

    user = await session.scalar(
        select(User)
        .options(
            selectinload(User.profile),
            selectinload(User.weekly_subscription),
            selectinload(User.career_plan).selectinload(CareerPlan.actions),
        )
        .where(User.telegram_user_id == telegram_user_id)
    )
    action = _next_best_action(
        telegram_user_id,
        user.profile if user is not None else None,
        user.career_plan if user is not None else None,
        user.weekly_subscription if user is not None else None,
        datastore,
    )

    if user is not None:
        event_source = _event_source(source)
        session.add(
            _product_event(
                user.id,
                "next_action_viewed",
                source=event_source,
                entity_type="next_best_action",
                entity_id=action.action_id,
                payload={"state": action.state, "profile_quality_score": action.profile_quality.score},
            )
        )
        if action.state in {
            "find_vacancy",
            "update_application_outcome",
            "enable_digest",
            "continue_plan",
        }:
            session.add(
                _product_event(
                    user.id,
                    "first_value_reached",
                    source=event_source,
                    entity_type="next_best_action",
                    entity_id=action.action_id,
                    payload={"state": action.state},
                )
            )
        await session.commit()

    return action


@router.get(
    "/{telegram_user_id}/evidence-packet",
    response_model=EvidencePacketOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_user_evidence_packet(
    telegram_user_id: int,
    request: Request,
    task: EvidenceTask = Query("skill_gap_explanation"),
    surface: EvidenceSurface = Query("web"),
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> EvidencePacketOut | JSONResponse:
    """Return the bounded evidence packet for a user-scoped explainer task."""

    return await _build_user_evidence_packet(
        telegram_user_id=telegram_user_id,
        task=task,
        surface=surface,
        request=request,
        session=session,
        datastore=datastore,
    )


@router.get(
    "/{telegram_user_id}/evidence-explainer",
    response_model=EvidenceExplainerOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_user_evidence_explainer(
    telegram_user_id: int,
    request: Request,
    task: EvidenceTask = Query("skill_gap_explanation"),
    surface: EvidenceSurface = Query("web"),
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> EvidenceExplainerOut | JSONResponse:
    """Return deterministic bounded copy from the evidence packet when the feature is enabled."""

    started_at = time.perf_counter()
    denial_reason = _evidence_explainer_denial_reason(settings, telegram_user_id)
    if denial_reason is not None:
        status = "not_allowed" if denial_reason == "not_allowed" else "disabled"
        _record_evidence_explainer_metrics(
            settings=settings,
            task=task,
            surface=surface,
            status=status,
            started_at=started_at,
        )
        if denial_reason == "not_allowed":
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "EVIDENCE_EXPLAINER_NOT_ALLOWED",
                    "message": "Evidence explainer is limited to approved internal users.",
                    "details": {"reason": denial_reason},
                },
            )
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "EVIDENCE_EXPLAINER_DISABLED",
                "message": "Evidence explainer is disabled for this runtime.",
                "details": {"reason": denial_reason},
            },
        )

    packet = await _build_user_evidence_packet(
        telegram_user_id=telegram_user_id,
        task=task,
        surface=surface,
        request=request,
        session=session,
        datastore=datastore,
    )
    if isinstance(packet, JSONResponse):
        _record_evidence_explainer_metrics(
            settings=settings,
            task=task,
            surface=surface,
            status="profile_missing",
            started_at=started_at,
        )
        return packet
    output = build_deterministic_explainer(packet)
    _record_evidence_explainer_metrics(
        settings=settings,
        task=task,
        surface=surface,
        status=output.status,
        started_at=started_at,
        blocked_claims=output.blocked_claims,
    )
    return output


@router.post(
    "/{telegram_user_id}/product-events",
    response_model=ProductEventOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def create_product_event(
    telegram_user_id: int,
    request: Request,
    payload: ProductEventIn,
    session: AsyncSession = Depends(get_db_session),
) -> ProductEventOut:
    """Record a PII-light product telemetry event from web, bot or workers."""

    try:
        async with session.begin():
            user = await _get_or_create_user(session, telegram_user_id)
            event = await record_product_event(
                session,
                user_id=user.id,
                event_name=payload.event_name,
                surface=payload.surface,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                request_id=getattr(request.state, "request_id", None),
                session_id=payload.session_id,
                correlation_id=payload.correlation_id,
                metadata=payload.metadata,
                occurred_at=payload.occurred_at,
            )
    except ProductEventValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_PRODUCT_EVENT",
                "message": str(exc),
                "details": {"event_name": payload.event_name},
            },
        ) from exc

    await session.refresh(event)
    return _product_event_out(event)


@router.get(
    "/{telegram_user_id}/commercial-state",
    response_model=CommercialStateOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_commercial_state(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> CommercialStateOut:
    """Return the user's current commercial plan and entitlements."""

    async with session.begin():
        user = await _get_or_create_user(session, telegram_user_id)
        account = await get_or_create_commercial_account(session, user)

    await session.refresh(account)
    return _commercial_state_out(account)


@router.delete(
    "/{telegram_user_id}/profile",
    response_model=None,
    response_class=Response,
    status_code=204,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def delete_user_profile(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> Response | JSONResponse:
    result = await session.execute(
        select(UserProfile).join(User, UserProfile.user_id == User.id).where(User.telegram_user_id == telegram_user_id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        return profile_not_found_error(telegram_user_id)

    session.add(_product_event(profile.user_id, "delete_completed", source="user", entity_type="profile"))
    await session.delete(profile)
    await session.commit()

    return Response(status_code=204)


@router.put(
    "/{telegram_user_id}/career-plan",
    response_model=CareerPlanOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def upsert_career_plan(
    telegram_user_id: int,
    payload: CareerPlanIn,
    session: AsyncSession = Depends(get_db_session),
) -> CareerPlanOut:
    """Create or replace the user's career plan baseline."""

    async with session.begin():
        user = await _get_or_create_user(session, telegram_user_id)
        profile = await _profile_for_user(session, user.id)
        plan = await session.scalar(select(CareerPlan).where(CareerPlan.user_id == user.id))

        target_role = payload.target_role
        target_grade = payload.target_grade
        target_city_tier = payload.target_city_tier
        target_country = payload.target_country
        target_region = payload.target_region
        target_city = payload.target_city
        target_geo_scope = payload.target_geo_scope
        target_work_mode = payload.target_work_mode
        target_domain = payload.target_domain
        if profile is not None:
            target_role = target_role if target_role is not None else profile.target_role
            target_grade = target_grade if target_grade is not None else profile.target_grade
            target_city_tier = target_city_tier if target_city_tier is not None else profile.target_city_tier
            target_country = target_country if target_country is not None else profile.target_country
            target_region = target_region if target_region is not None else profile.target_region
            target_city = target_city if target_city is not None else profile.target_city
            target_geo_scope = target_geo_scope if target_geo_scope is not None else profile.target_geo_scope
            target_work_mode = target_work_mode if target_work_mode is not None else profile.target_work_mode
            target_domain = target_domain if target_domain is not None else profile.target_domain

        if plan is None:
            plan = CareerPlan(user_id=user.id)
            session.add(plan)
        plan.target_role = target_role
        plan.target_grade = target_grade
        plan.target_city_tier = target_city_tier
        plan.target_country = target_country
        plan.target_region = target_region
        plan.target_city = target_city
        plan.target_geo_scope = target_geo_scope
        plan.target_work_mode = target_work_mode
        plan.target_domain = target_domain
        plan.status = payload.status
        plan.notes = payload.notes

    user, plan = await _get_user_with_career_plan(session, telegram_user_id)
    assert user is not None and plan is not None  # noqa: S101
    return _career_plan_out(user, plan)


@router.get(
    "/{telegram_user_id}/career-plan",
    response_model=CareerPlanOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_career_plan(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> CareerPlanOut | JSONResponse:
    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    user, plan = result
    return _career_plan_out(user, plan)


@router.delete(
    "/{telegram_user_id}/career-plan",
    response_model=None,
    response_class=Response,
    status_code=204,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def delete_career_plan(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> Response | JSONResponse:
    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    _user, plan = result

    await session.delete(plan)
    await session.commit()
    return Response(status_code=204)


@router.patch(
    "/{telegram_user_id}/career-plan",
    response_model=CareerPlanOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def patch_career_plan(
    telegram_user_id: int,
    payload: CareerPlanPatch,
    session: AsyncSession = Depends(get_db_session),
) -> CareerPlanOut | JSONResponse:
    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    _user, plan = result

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    await session.commit()

    user, refreshed_plan = await _get_user_with_career_plan(session, telegram_user_id)
    assert user is not None and refreshed_plan is not None  # noqa: S101
    return _career_plan_out(user, refreshed_plan)


@router.post(
    "/{telegram_user_id}/career-plan/actions",
    response_model=CareerActionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def create_career_action(
    telegram_user_id: int,
    payload: CareerActionIn,
    session: AsyncSession = Depends(get_db_session),
) -> CareerActionOut | JSONResponse:
    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    user, plan = result

    now = datetime.now(timezone.utc)
    action = CareerAction(
        plan_id=plan.id,
        title=payload.title,
        description=payload.description,
        action_type=payload.action_type,
        status=payload.status,
        priority=payload.priority,
        skill_name=payload.skill_name,
        hh_vacancy_id=payload.hh_vacancy_id,
        vacancy_title=payload.vacancy_title,
        vacancy_url=payload.vacancy_url,
        recommendation_source=payload.recommendation_source or "manual",
        dataset_run_id=payload.dataset_run_id,
        reason=payload.reason,
        expected_impact=payload.expected_impact,
        effort_estimate=payload.effort_estimate,
        due_date=payload.due_date,
        evidence=payload.evidence,
        application_status=payload.application_status,
        completed_at=now if payload.status == "done" else None,
    )
    session.add(action)
    CAREER_ACTIONS_TOTAL.labels(
        action_type=_bounded_label(payload.action_type, CAREER_ACTION_LABELS),
        recommendation_source=_bounded_label(payload.recommendation_source or "manual", RECOMMENDATION_SOURCE_LABELS),
    ).inc()
    session.add(
        _product_event(
            user.id,
            "action_created",
            source=_event_source(payload.source),
            entity_type="career_action",
            payload={
                "action_type": payload.action_type,
                "generated": payload.recommendation_source not in {None, "manual"},
            },
        )
    )
    await session.commit()
    await session.refresh(action)
    return _career_action_out(action)


@router.patch(
    "/{telegram_user_id}/career-plan/actions/{action_id}",
    response_model=CareerActionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def patch_career_action(
    telegram_user_id: int,
    action_id: int,
    payload: CareerActionPatch,
    session: AsyncSession = Depends(get_db_session),
) -> CareerActionOut | JSONResponse:
    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    user, plan = result
    action = await session.scalar(
        select(CareerAction).where(CareerAction.id == action_id, CareerAction.plan_id == plan.id)
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Career action not found")

    update = payload.model_dump(exclude_unset=True)
    event_source = update.pop("source", None)
    for field, value in update.items():
        setattr(action, field, value)
    if "status" in update:
        session.add(
            _product_event(
                user.id,
                "plan_action_status_updated",
                source=_event_source(event_source),
                entity_type="career_action",
                entity_id=str(action.id),
                payload={"status": action.status, "action_type": action.action_type},
            )
        )
    if update.get("status") == "done" and action.completed_at is None:
        action.completed_at = datetime.now(timezone.utc)
        session.add(_product_event(user.id, "action_completed", entity_type="career_action", entity_id=str(action.id)))
    elif update.get("status") in {"planned", "in_progress", "skipped"}:
        action.completed_at = None

    await session.commit()
    await session.refresh(action)
    return _career_action_out(action)


@router.post(
    "/{telegram_user_id}/career-plan/generate-actions",
    response_model=CareerPlanOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def generate_career_plan_actions(
    telegram_user_id: int,
    payload: CareerPlanGenerateActionsIn,
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> CareerPlanOut | JSONResponse:
    """Generate evidence-backed plan actions from the user's skill-gap."""

    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    user, plan = result
    await ensure_user_entitlement(session, user, ENTITLEMENT_CAREER_PLAN_GENERATE)
    profile = await _profile_for_user(session, user.id)
    if profile is None:
        return profile_not_found_error(telegram_user_id)

    analysis = await compute_persona_analysis(datastore, _persona_profile_from_user_profile(user, profile))
    if not isinstance(analysis, PersonaAnalysisResponse):
        return analysis

    dataset_run_id = _dataset_run_id(datastore)
    generated_count = 0
    existing_generated = [
        action
        for action in plan.actions
        if action.recommendation_source == "skill_gap" and action.status in {"planned", "in_progress"}
    ]
    if payload.replace_generated:
        for action in existing_generated:
            await session.delete(action)
        await session.flush()
        existing_generated = []

    existing_skill_actions = {
        (action.skill_name or "").strip().lower()
        for action in plan.actions
        if action.status not in {"done", "skipped"} and action.skill_name
    }
    today = date.today()
    for index, skill in enumerate(analysis.recommended_skills[: payload.limit], start=1):
        key = skill.strip().lower()
        if not key or key in existing_skill_actions:
            continue
        evidence = next(
            (entry.model_dump(mode="json") for entry in analysis.skill_gap if entry.skill_name == skill),
            {},
        )
        action = CareerAction(
            plan_id=plan.id,
            title=f"Close {skill} skill gap",
            description=f"Add practice around {skill} for the target role.",
            action_type="learning",
            status="planned",
            priority=index * 10,
            skill_name=skill,
            recommendation_source="skill_gap",
            dataset_run_id=dataset_run_id,
            reason=f"{skill} is a recommended gap for {profile.target_role or 'the target role'}.",
            expected_impact="Improves fit for vacancies in the selected segment",
            effort_estimate="medium",
            due_date=today + timedelta(days=14 * index),
            evidence=evidence,
        )
        session.add(action)
        CAREER_ACTIONS_TOTAL.labels(action_type="learning", recommendation_source="skill_gap").inc()
        existing_skill_actions.add(key)
        generated_count += 1

    session.add(
        _product_event(
            user.id,
            "plan_actions_generated",
            source=_event_source(payload.source),
            entity_type="career_plan",
            entity_id=str(plan.id),
            payload={"generated_count": generated_count, "dataset_run_id": dataset_run_id},
        )
    )
    await session.commit()
    session.expire_all()

    refreshed_user, refreshed_plan = await _get_user_with_career_plan(session, telegram_user_id)
    assert refreshed_user is not None and refreshed_plan is not None  # noqa: S101
    return _career_plan_out(refreshed_user, refreshed_plan)


@router.post(
    "/{telegram_user_id}/career-plan/saved-vacancies",
    response_model=CareerActionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def save_vacancy_to_career_plan(
    telegram_user_id: int,
    payload: SavedVacancyIn,
    session: AsyncSession = Depends(get_db_session),
) -> CareerActionOut | JSONResponse:
    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    user, plan = result
    source = _event_source(payload.source)

    existing_action = await session.scalar(
        select(CareerAction)
        .where(
            CareerAction.plan_id == plan.id,
            CareerAction.action_type == "saved_vacancy",
            CareerAction.hh_vacancy_id == payload.hh_vacancy_id,
        )
        .order_by(CareerAction.id.asc())
    )
    if existing_action is not None:
        existing_action.title = f"Apply to {payload.title}"
        existing_action.description = payload.note
        existing_action.vacancy_title = payload.title
        existing_action.vacancy_url = payload.url
        existing_action.application_status = existing_action.application_status or "saved"
        await session.commit()
        await session.refresh(existing_action)
        return _career_action_out(existing_action)

    action = CareerAction(
        plan_id=plan.id,
        title=f"Apply to {payload.title}",
        description=payload.note,
        action_type="saved_vacancy",
        status="planned",
        application_status="saved",
        priority=50,
        hh_vacancy_id=payload.hh_vacancy_id,
        vacancy_title=payload.title,
        vacancy_url=payload.url,
    )
    session.add(action)
    CAREER_ACTIONS_TOTAL.labels(action_type="saved_vacancy", recommendation_source="manual").inc()
    session.add(
        ApplicationOutcomeEvent(
            user_id=user.id,
            action=action,
            hh_vacancy_id=payload.hh_vacancy_id,
            vacancy_title=payload.title,
            vacancy_url=payload.url,
            status="saved",
            source=source,
            note=payload.note,
            occurred_at=datetime.now(timezone.utc),
        )
    )
    APPLICATION_OUTCOMES_TOTAL.labels(status="saved", source=source).inc()
    session.add(
        _product_event(
            user.id,
            "vacancy_saved",
            source=source,
            entity_type="vacancy",
            entity_id=payload.hh_vacancy_id,
            payload={"has_note": payload.note is not None},
        )
    )
    await session.commit()
    await session.refresh(action)
    return _career_action_out(action)


@router.post(
    "/{telegram_user_id}/career-plan/actions/{action_id}/outcome",
    response_model=CareerActionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def update_application_outcome(
    telegram_user_id: int,
    action_id: int,
    payload: ApplicationOutcomeIn,
    session: AsyncSession = Depends(get_db_session),
) -> CareerActionOut | JSONResponse:
    """Record a vacancy/application funnel transition for a plan action."""

    result = await _get_required_career_plan(session, telegram_user_id)
    if isinstance(result, JSONResponse):
        return result
    user, plan = result
    action = await session.scalar(
        select(CareerAction).where(CareerAction.id == action_id, CareerAction.plan_id == plan.id)
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Career action not found")

    now = datetime.now(timezone.utc)
    source = _event_source(payload.source, default="user")
    action.application_status = payload.status
    if payload.status in {"applied", "interview"} and action.status == "planned":
        action.status = "in_progress"
    elif payload.status in {"offer", "rejected", "withdrawn"}:
        action.status = "done" if payload.status == "offer" else "skipped"
        action.completed_at = action.completed_at or now

    session.add(
        ApplicationOutcomeEvent(
            user_id=user.id,
            action_id=action.id,
            hh_vacancy_id=action.hh_vacancy_id,
            vacancy_title=action.vacancy_title,
            vacancy_url=action.vacancy_url,
            status=payload.status,
            source=source,
            note=payload.note,
            occurred_at=now,
        )
    )
    APPLICATION_OUTCOMES_TOTAL.labels(
        status=_bounded_label(payload.status, APPLICATION_OUTCOME_LABELS),
        source=source,
    ).inc()
    session.add(
        _product_event(
            user.id,
            "application_outcome",
            source=source,
            entity_type="career_action",
            entity_id=str(action.id),
            payload={"status": payload.status, "hh_vacancy_id": action.hh_vacancy_id},
        )
    )
    await session.commit()
    await session.refresh(action)
    return _career_action_out(action)


@router.post(
    "/{telegram_user_id}/api-key",
    response_model=UserApiKeyOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def create_user_api_key(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> UserApiKeyOut:
    plaintext, key_hash, key_prefix = _generate_api_key(telegram_user_id)
    now = datetime.now(timezone.utc)

    async with session.begin():
        user = await _get_or_create_user(session, telegram_user_id)
        active_key = await _active_api_key(session, user.id)
        if active_key is not None:
            active_key.revoked_at = now

        api_key = UserApiKey(user_id=user.id, key_hash=key_hash, key_prefix=key_prefix)
        session.add(api_key)
        session.add(_product_event(user.id, "api_key_created", source="api", entity_type="api_key"))

    await session.refresh(api_key)
    return UserApiKeyOut(key=plaintext, key_prefix=api_key.key_prefix, created_at=api_key.created_at)


@router.get(
    "/{telegram_user_id}/api-key",
    response_model=UserApiKeyStatusOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def get_user_api_key_status(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> UserApiKeyStatusOut | JSONResponse:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return profile_not_found_error(telegram_user_id)

    api_key = await _active_api_key(session, user.id)
    if api_key is None:
        return JSONResponse(status_code=404, content={"error": "Active API key not found"})

    return UserApiKeyStatusOut(
        key_prefix=api_key.key_prefix,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        is_active=api_key.revoked_at is None,
    )


@router.delete(
    "/{telegram_user_id}/api-key",
    response_model=UserApiKeyRevokeOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def revoke_user_api_key(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> UserApiKeyRevokeOut | JSONResponse:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return profile_not_found_error(telegram_user_id)

    api_key = await _active_api_key(session, user.id)
    if api_key is None:
        return JSONResponse(status_code=404, content={"error": "Active API key not found"})

    revoked_at = datetime.now(timezone.utc)
    api_key.revoked_at = revoked_at
    session.add(_product_event(user.id, "api_key_revoked", source="api", entity_type="api_key"))
    await session.commit()
    return UserApiKeyRevokeOut(revoked=True, revoked_at=revoked_at)


@auth_router.get(
    "/me",
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    telegram_user_id = getattr(request.state, "telegram_user_id", None)
    if telegram_user_id is None:
        raise HTTPException(status_code=403, detail="User API key required")

    result = await session.execute(
        select(User, UserProfile)
        .join(UserProfile, User.id == UserProfile.user_id, isouter=True)
        .where(User.telegram_user_id == telegram_user_id)
    )
    row = result.first()
    if not row:
        return JSONResponse(content={"telegram_user_id": telegram_user_id, "profile": None})

    user, profile = row
    profile_payload = _profile_out(user, profile).model_dump(mode="json") if profile else None
    return JSONResponse(content={"telegram_user_id": telegram_user_id, "profile": profile_payload})


@auth_router.get(
    "/me/api-key",
    response_model=UserApiKeyStatusOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def get_current_user_api_key_status(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> UserApiKeyStatusOut | JSONResponse:
    telegram_user_id = getattr(request.state, "telegram_user_id", None)
    if telegram_user_id is None:
        raise HTTPException(status_code=403, detail="User API key required")

    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return profile_not_found_error(telegram_user_id)

    api_key = await _active_api_key(session, user.id)
    if api_key is None:
        return JSONResponse(status_code=404, content={"error": "Active API key not found"})

    return UserApiKeyStatusOut(
        key_prefix=api_key.key_prefix,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        is_active=api_key.revoked_at is None,
    )


@auth_router.delete(
    "/me/api-key",
    response_model=UserApiKeyRevokeOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_user_or_service_token)],
)
async def revoke_current_user_api_key(
    request: Request,
    source: str | None = Query("web", description="Product event source"),
    session: AsyncSession = Depends(get_db_session),
) -> UserApiKeyRevokeOut | JSONResponse:
    telegram_user_id = getattr(request.state, "telegram_user_id", None)
    if telegram_user_id is None:
        raise HTTPException(status_code=403, detail="User API key required")

    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return profile_not_found_error(telegram_user_id)

    api_key = await _active_api_key(session, user.id)
    if api_key is None:
        return JSONResponse(status_code=404, content={"error": "Active API key not found"})

    revoked_at = datetime.now(timezone.utc)
    api_key.revoked_at = revoked_at
    session.add(_product_event(user.id, "api_key_revoked", source=_event_source(source), entity_type="api_key"))
    await session.commit()
    return UserApiKeyRevokeOut(revoked=True, revoked_at=revoked_at)


@router.post(
    "/{telegram_user_id}/resume",
    response_model=ResumeUploadOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def upload_user_resume(
    telegram_user_id: int,
    request: Request,
    filename: str | None = Query(None, description="Filename for raw application/pdf uploads"),
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> ResumeUploadOut:
    """Upload a PDF resume and persist extracted skills."""

    original_filename, content_type, content = await _read_resume_upload(request, filename)
    if content_type != "application/pdf":
        raise HTTPException(
            status_code=422,
            detail={"error_code": "INVALID_RESUME_TYPE", "message": "Only PDF resumes are supported.", "details": {}},
        )
    if len(content) > settings.max_resume_bytes:
        raise HTTPException(
            status_code=413,
            detail={"error_code": "RESUME_TOO_LARGE", "message": "Resume exceeds maximum size.", "details": {}},
        )

    parser_result = await parse_pdf_resume(content, _known_skills(datastore))
    skills_value = parser_result.get("skills", [])
    extracted_skills = [str(skill) for skill in skills_value] if isinstance(skills_value, list) else []
    storage_service = _storage_service(request, settings)
    try:
        s3_key = await storage_service.upload_resume(telegram_user_id, content, content_type)
    except StorageNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="Resume storage is not configured") from exc

    previous_s3_key: str | None = None
    async with session.begin():
        user = await _get_or_create_user(session, telegram_user_id)
        existing = await session.scalar(select(UserResume).where(UserResume.user_id == user.id))
        if existing is not None:
            previous_s3_key = existing.s3_key
            await session.delete(existing)
            await session.flush()
        session.add(
            UserResume(
                user_id=user.id,
                s3_key=s3_key,
                original_filename=original_filename,
                content_type=content_type,
                file_size_bytes=len(content),
                extracted_skills=json.dumps(extracted_skills, ensure_ascii=False),
            )
        )

    if previous_s3_key and previous_s3_key != s3_key:
        try:
            await storage_service.delete_resume(previous_s3_key)
        except StorageNotConfiguredError:
            pass
        except Exception:
            logger.exception("Failed to delete replaced resume object", extra={"telegram_user_id": telegram_user_id})

    return ResumeUploadOut(
        telegram_user_id=telegram_user_id,
        s3_key=s3_key,
        original_filename=original_filename,
        content_type=content_type,
        file_size_bytes=len(content),
        extracted_skills=extracted_skills,
    )


@router.get(
    "/{telegram_user_id}/resume",
    response_model=ResumeStatusOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_user_resume(
    telegram_user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dependency),
) -> ResumeStatusOut:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        return ResumeStatusOut(uploaded=False)

    resume = await session.scalar(
        select(UserResume).where(UserResume.user_id == user.id).order_by(UserResume.id.desc())
    )
    if resume is None:
        return ResumeStatusOut(uploaded=False)

    try:
        presigned_url = await _storage_service(request, settings).get_resume_presigned_url(resume.s3_key, ttl=86400)
    except StorageNotConfiguredError:
        presigned_url = None
    return ResumeStatusOut(
        uploaded=True,
        telegram_user_id=telegram_user_id,
        s3_key=resume.s3_key,
        original_filename=resume.original_filename,
        content_type=resume.content_type,
        file_size_bytes=resume.file_size_bytes,
        uploaded_at=resume.uploaded_at,
        extracted_skills=_resume_skills(resume.extracted_skills),
        presigned_url=presigned_url,
    )


@router.get(
    "/{telegram_user_id}/resume/presigned-url",
    response_model=ResumePresignedUrlOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_user_resume_presigned_url(
    telegram_user_id: int,
    request: Request,
    ttl: int = Query(86400, ge=60, le=86400),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dependency),
) -> ResumePresignedUrlOut:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    resume = await session.scalar(
        select(UserResume).where(UserResume.user_id == user.id).order_by(UserResume.id.desc())
    )
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    try:
        url = await _storage_service(request, settings).get_resume_presigned_url(resume.s3_key, ttl=ttl)
    except StorageNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="Resume storage is not configured") from exc
    return ResumePresignedUrlOut(url=url, ttl=ttl)


@router.delete(
    "/{telegram_user_id}/resume",
    response_model=None,
    response_class=Response,
    status_code=204,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def delete_user_resume(
    telegram_user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dependency),
) -> Response:
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user is not None:
        resume = await session.scalar(select(UserResume).where(UserResume.user_id == user.id))
        if resume is not None:
            try:
                await _storage_service(request, settings).delete_resume(resume.s3_key)
            except StorageNotConfiguredError:
                pass
            await session.delete(resume)
            await session.commit()
    return Response(status_code=204)


async def _count_scalar(session: AsyncSession, statement: Any) -> int:
    return int((await session.scalar(statement)) or 0)


async def _grouped_counts(
    session: AsyncSession,
    key_column: Any,
    count_column: Any,
    *filters: Any,
) -> dict[str, int]:
    statement = select(key_column, func.count(count_column))
    for condition in filters:
        statement = statement.where(condition)
    rows = await session.execute(statement.group_by(key_column))
    return {str(key): int(count) for key, count in rows.all() if key is not None}


async def _distinct_user_counts_by_source(
    session: AsyncSession,
    *filters: Any,
) -> dict[str, int]:
    statement = select(ProductEvent.source, func.count(func.distinct(ProductEvent.user_id))).where(
        ProductEvent.source.in_(USER_ACTIVATION_EVENT_SOURCES)
    )
    for condition in filters:
        statement = statement.where(condition)
    rows = await session.execute(statement.group_by(ProductEvent.source))
    return {str(source): int(count) for source, count in rows.all() if source is not None}


async def _distinct_user_counts_by_source_for_events(
    session: AsyncSession,
    event_types: set[str],
    since: datetime,
) -> dict[str, int]:
    return await _distinct_user_counts_by_source(
        session,
        ProductEvent.occurred_at >= since,
        ProductEvent.event_type.in_(event_types),
    )


def _conversion_rates(numerator: dict[str, int], denominator: dict[str, int]) -> dict[str, float]:
    rates: dict[str, float] = {}
    for source, count in numerator.items():
        base = denominator.get(source, 0)
        rates[source] = round(count / base, 4) if base else 0.0
    return rates


def _cohort_week(value: datetime) -> date:
    value_utc = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    current_date = value_utc.date()
    return current_date - timedelta(days=current_date.weekday())


def _event_payload(event: ProductEvent) -> dict[str, object]:
    return event.payload if isinstance(event.payload, dict) else {}


def _trust_tier_from_event(event: ProductEvent) -> str | None:
    payload = _event_payload(event)
    explicit_tier = payload.get("trust_tier")
    if explicit_tier:
        return str(explicit_tier)
    if payload.get("search_state") not in {None, "ready"}:
        return "degraded_search"
    return None


async def _trust_tier_distribution(session: AsyncSession, since: datetime) -> dict[str, int]:
    events = (
        await session.scalars(
            select(ProductEvent).where(
                ProductEvent.occurred_at >= since,
                ProductEvent.source.in_(USER_ACTIVATION_EVENT_SOURCES),
            )
        )
    ).all()
    counts: dict[str, int] = {}
    for event in events:
        trust_tier = _trust_tier_from_event(event)
        if trust_tier:
            counts[trust_tier] = counts.get(trust_tier, 0) + 1
    return counts


async def _cohort_summaries(
    session: AsyncSession,
    *,
    since: datetime,
) -> list[ProductCohortSummaryOut]:
    user_rows = (await session.execute(select(User.id, User.created_at))).all()
    user_cohort: dict[int, date] = {user_id: _cohort_week(created_at) for user_id, created_at in user_rows}
    cohorts: dict[date, dict[str, object]] = {}

    def ensure(cohort_week: date) -> dict[str, object]:
        return cohorts.setdefault(
            cohort_week,
            {
                "users_started": set(),
                "active_users": set(),
                "profiles_completed_users": set(),
                "first_value_users": set(),
                "weekly_return_users": set(),
                "digest_engagement_users": set(),
                "digest_subscribers": set(),
                "events_by_surface": {},
            },
        )

    for user_id, cohort_week in user_cohort.items():
        ensure(cohort_week)["users_started"].add(user_id)  # type: ignore[union-attr]

    active_subscription_user_ids = (
        await session.scalars(select(WeeklySubscription.user_id).where(WeeklySubscription.active.is_(True)))
    ).all()
    for user_id in active_subscription_user_ids:
        cohort_week = user_cohort.get(user_id)
        if cohort_week is not None:
            ensure(cohort_week)["digest_subscribers"].add(user_id)  # type: ignore[union-attr]

    events = (
        await session.scalars(
            select(ProductEvent).where(
                ProductEvent.occurred_at >= since,
                ProductEvent.source.in_(USER_ACTIVATION_EVENT_SOURCES),
            )
        )
    ).all()
    for event in events:
        cohort_week = user_cohort.get(event.user_id)
        if cohort_week is None:
            continue
        bucket = ensure(cohort_week)
        bucket["active_users"].add(event.user_id)  # type: ignore[union-attr]
        events_by_surface = bucket["events_by_surface"]
        if isinstance(events_by_surface, dict):
            source = str(event.source or "unknown")
            events_by_surface[source] = int(events_by_surface.get(source, 0)) + 1
        if event.event_type == "profile_completed":
            bucket["profiles_completed_users"].add(event.user_id)  # type: ignore[union-attr]
        if event.event_type == "first_value_reached":
            bucket["first_value_users"].add(event.user_id)  # type: ignore[union-attr]
        if event.event_type in {"weekly_return", "weekly_returned"}:
            bucket["weekly_return_users"].add(event.user_id)  # type: ignore[union-attr]
        if event.event_type in {"digest_engagement", "digest_preview_viewed", "digest_opened"}:
            bucket["digest_engagement_users"].add(event.user_id)  # type: ignore[union-attr]

    return [
        ProductCohortSummaryOut(
            cohort_week=cohort_week,
            users_started=len(bucket["users_started"]),  # type: ignore[arg-type]
            active_users=len(bucket["active_users"]),  # type: ignore[arg-type]
            profiles_completed_users=len(bucket["profiles_completed_users"]),  # type: ignore[arg-type]
            first_value_users=len(bucket["first_value_users"]),  # type: ignore[arg-type]
            weekly_return_users=len(bucket["weekly_return_users"]),  # type: ignore[arg-type]
            digest_engagement_users=len(bucket["digest_engagement_users"]),  # type: ignore[arg-type]
            digest_subscribers=len(bucket["digest_subscribers"]),  # type: ignore[arg-type]
            events_by_surface=dict(bucket["events_by_surface"]),  # type: ignore[arg-type]
        )
        for cohort_week, bucket in sorted(cohorts.items(), reverse=True)
    ]


@admin_router.get(
    "/product-loop-summary",
    response_model=ProductLoopSummaryOut,
    response_class=JSONResponse,
)
async def product_loop_summary(
    days: int = Query(30, ge=1, le=366),
    session: AsyncSession = Depends(get_db_session),
) -> ProductLoopSummaryOut:
    """Return a compact PM funnel summary for the guided career loop."""

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    users_total = await _count_scalar(session, select(func.count(User.id)))
    profiles_total = await _count_scalar(session, select(func.count(UserProfile.id)))
    career_plans_total = await _count_scalar(session, select(func.count(CareerPlan.id)))
    active_subscriptions_total = await _count_scalar(
        session,
        select(func.count(WeeklySubscription.id)).where(WeeklySubscription.active.is_(True)),
    )
    recent_active_users = await _count_scalar(
        session,
        select(func.count(func.distinct(ProductEvent.user_id))).where(ProductEvent.occurred_at >= since),
    )
    users_with_saved_vacancy = await _count_scalar(
        session,
        select(func.count(func.distinct(CareerPlan.user_id)))
        .join(CareerAction, CareerAction.plan_id == CareerPlan.id)
        .where(CareerAction.action_type == "saved_vacancy"),
    )
    users_with_application_outcome = await _count_scalar(
        session,
        select(func.count(func.distinct(ApplicationOutcomeEvent.user_id))),
    )
    career_actions_total = await _count_scalar(session, select(func.count(CareerAction.id)))
    completed_actions_total = await _count_scalar(
        session,
        select(func.count(CareerAction.id)).where(CareerAction.status == "done"),
    )
    saved_vacancies_total = await _count_scalar(
        session,
        select(func.count(CareerAction.id)).where(CareerAction.action_type == "saved_vacancy"),
    )
    application_outcomes_total = await _count_scalar(session, select(func.count(ApplicationOutcomeEvent.id)))
    recent_application_outcomes_total = await _count_scalar(
        session,
        select(func.count(ApplicationOutcomeEvent.id)).where(ApplicationOutcomeEvent.occurred_at >= since),
    )
    active_users_by_source = await _distinct_user_counts_by_source(
        session,
        ProductEvent.occurred_at >= since,
    )
    activation_users_by_source = await _distinct_user_counts_by_source_for_events(
        session,
        {"profile_completed", "next_action_viewed", "first_session_step_clicked"},
        since,
    )
    first_value_users_by_source = await _distinct_user_counts_by_source(
        session,
        ProductEvent.occurred_at >= since,
        ProductEvent.event_type == "first_value_reached",
    )

    return ProductLoopSummaryOut(
        window_days=days,
        generated_at=now,
        users_total=users_total,
        profiles_total=profiles_total,
        career_plans_total=career_plans_total,
        active_subscriptions_total=active_subscriptions_total,
        recent_active_users=recent_active_users,
        users_with_saved_vacancy=users_with_saved_vacancy,
        users_with_application_outcome=users_with_application_outcome,
        career_actions_total=career_actions_total,
        completed_actions_total=completed_actions_total,
        saved_vacancies_total=saved_vacancies_total,
        application_outcomes_total=application_outcomes_total,
        recent_application_outcomes_total=recent_application_outcomes_total,
        recent_product_events_by_type=await _grouped_counts(
            session,
            ProductEvent.event_type,
            ProductEvent.id,
            ProductEvent.occurred_at >= since,
        ),
        recent_product_events_by_source=await _grouped_counts(
            session,
            ProductEvent.source,
            ProductEvent.id,
            ProductEvent.occurred_at >= since,
        ),
        activation_events_by_source=await _grouped_counts(
            session,
            ProductEvent.source,
            ProductEvent.id,
            ProductEvent.occurred_at >= since,
            ProductEvent.source.in_(USER_ACTIVATION_EVENT_SOURCES),
            ProductEvent.event_type.in_({"profile_completed", "next_action_viewed"}),
        ),
        first_value_users_by_source=first_value_users_by_source,
        activation_conversion_by_source=_conversion_rates(activation_users_by_source, active_users_by_source),
        first_value_conversion_by_source=_conversion_rates(first_value_users_by_source, active_users_by_source),
        weekly_return_users_by_source=await _distinct_user_counts_by_source_for_events(
            session,
            {"weekly_return", "weekly_returned"},
            since,
        ),
        digest_engagement_users_by_source=await _distinct_user_counts_by_source_for_events(
            session,
            {"digest_engagement", "digest_preview_viewed", "digest_opened"},
            since,
        ),
        trust_tier_distribution=await _trust_tier_distribution(session, since),
        degraded_search_exposures=await _count_scalar(
            session,
            select(func.count(ProductEvent.id)).where(
                ProductEvent.occurred_at >= since,
                ProductEvent.event_type == "search_degraded_warning_shown",
            ),
        ),
        cohort_weeks=await _cohort_summaries(session, since=since),
        career_actions_by_type=await _grouped_counts(session, CareerAction.action_type, CareerAction.id),
        career_actions_by_recommendation_source=await _grouped_counts(
            session,
            CareerAction.recommendation_source,
            CareerAction.id,
        ),
        recent_application_outcomes_by_status=await _grouped_counts(
            session,
            ApplicationOutcomeEvent.status,
            ApplicationOutcomeEvent.id,
            ApplicationOutcomeEvent.occurred_at >= since,
        ),
    )


@admin_router.get(
    "/users",
    response_model=list[UserSummaryOut],
    response_class=JSONResponse,
)
async def list_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[UserSummaryOut]:
    """List registered users for admin operations."""

    result = await session.execute(
        select(User, UserProfile.id, WeeklySubscription.id)
        .join(UserProfile, UserProfile.user_id == User.id, isouter=True)
        .join(WeeklySubscription, WeeklySubscription.user_id == User.id, isouter=True)
        .order_by(User.id)
        .offset(skip)
        .limit(limit)
    )
    return [
        UserSummaryOut(
            id=user.id,
            telegram_user_id=user.telegram_user_id,
            username=user.username,
            created_at=user.created_at,
            has_profile=profile_id is not None,
            has_subscription=subscription_id is not None,
        )
        for user, profile_id, subscription_id in result.all()
    ]
