import json
from datetime import date, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from skillra_api.config import get_settings
from skillra_api.datastore import DataStore
from skillra_api.db.models import MarketSnapshot
from skillra_api.deps import get_datastore_dependency
from skillra_api.deps.auth import require_user_or_service_token
from skillra_api.limiter import limiter
from skillra_api.schemas import (
    CareerGraphOut,
    CareerTransitionOut,
    SalaryTrendOut,
    SegmentFilters,
    SegmentSummary,
    SkillDemandTrendOut,
    TrendDataPoint,
    VacancyCountTrendOut,
)
from skillra_api.services.analytics import compute_segment_summary
from skillra_api.services.snapshot_service import snapshots_to_frame
from skillra_api.services.trust import dataset_trust_payload
from skillra_pda.ingest.source_registry import TREND_BLOCKED_USER_MESSAGE
from skillra_pda.timeseries import compute_salary_trend, compute_skill_demand_trend

router = APIRouter(prefix="/v1", dependencies=[Depends(require_user_or_service_token)], tags=["market"])

GRADE_ORDER = ["junior", "jun", "middle", "senior", "lead", "principal"]
GRADE_RANK = {grade: index for index, grade in enumerate(GRADE_ORDER)}


@router.post(
    "/market/segment-summary",
    response_model=SegmentSummary,
    response_class=JSONResponse,
)
@limiter.limit(get_settings().rate_limit_market)
async def segment_summary(
    request: Request,  # noqa: ARG001
    filters: SegmentFilters,
    datastore: DataStore = Depends(get_datastore_dependency),
) -> SegmentSummary | JSONResponse:
    """Return aggregated statistics for a market segment defined by filters."""

    summary = await compute_segment_summary(datastore, filters)
    if isinstance(summary, SegmentSummary):
        return summary.model_copy(
            update=dataset_trust_payload(
                datastore,
                sample_size=summary.sample_size or summary.vacancy_count,
                confidence=summary.confidence,
            )
        )
    return summary


@router.get("/market/trends/salary", response_model=SalaryTrendOut, response_class=JSONResponse)
async def salary_trend(
    request: Request,
    role: str = Query(..., min_length=1),
    grade: str = Query(..., min_length=1),
    weeks: int = Query(12, ge=1, le=104),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> SalaryTrendOut:
    trend_trust, trend_ready = _trend_trust(datastore)
    if not trend_ready:
        return SalaryTrendOut(role=role, grade=grade, data=[], **trend_trust)

    history = await _history_df(request, datastore)
    trend = compute_salary_trend(history, role, grade, weeks=weeks)
    source_counts = _weekly_source_counts(history, role=role, grade=grade)
    dataset_run_id = _dataset_run_id(datastore)
    return SalaryTrendOut(
        role=role,
        grade=grade,
        **trend_trust,
        data=[
            _trend_point(
                week_start=row.week_start,
                value=float(row.salary_p50),
                dataset_run_id=dataset_run_id,
                source_row_count=source_counts.get(_week_key(row.week_start)),
            )
            for row in trend.itertuples()
        ],
    )


@router.get("/market/trends/skill-demand", response_model=SkillDemandTrendOut, response_class=JSONResponse)
async def skill_demand_trend(
    request: Request,
    skill: str = Query(..., min_length=1),
    role: str | None = Query(None),
    grade: str | None = Query(None),
    weeks: int = Query(12, ge=1, le=104),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> SkillDemandTrendOut:
    trend_trust, trend_ready = _trend_trust(datastore)
    if not trend_ready:
        return SkillDemandTrendOut(skill=skill, role=role, data=[], **trend_trust)

    history = await _history_df(request, datastore)
    trend = compute_skill_demand_trend(history, skill, role=role, grade=grade, weeks=weeks)
    dataset_run_id = _dataset_run_id(datastore)
    return SkillDemandTrendOut(
        skill=skill,
        role=role,
        **trend_trust,
        data=[
            _trend_point(
                week_start=row.week_start,
                value=float(row.vacancy_count),
                dataset_run_id=dataset_run_id,
                source_row_count=_int_or_none(row.vacancy_count),
            )
            for row in trend.itertuples()
        ],
    )


@router.get("/market/trends/vacancy-count", response_model=VacancyCountTrendOut, response_class=JSONResponse)
async def vacancy_count_trend(
    request: Request,
    role: str = Query(..., min_length=1),
    grade: str | None = Query(None),
    weeks: int = Query(12, ge=1, le=104),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> VacancyCountTrendOut:
    trend_trust, trend_ready = _trend_trust(datastore)
    if not trend_ready:
        return VacancyCountTrendOut(role=role, grade=grade, data=[], **trend_trust)

    history = await _history_df(request, datastore)
    if role and not history.empty:
        history = history[history["role"] == role]
    if grade and not history.empty:
        history = history[history["grade"] == grade]
    if history.empty:
        data: list[TrendDataPoint] = []
    else:
        trend = history.groupby("week_start", observed=True)["vacancy_count"].sum().reset_index().tail(weeks)
        dataset_run_id = _dataset_run_id(datastore)
        data = [
            _trend_point(
                week_start=row.week_start,
                value=float(row.vacancy_count),
                dataset_run_id=dataset_run_id,
                source_row_count=_int_or_none(row.vacancy_count),
            )
            for row in trend.itertuples()
        ]
    return VacancyCountTrendOut(role=role, grade=grade, data=data, **trend_trust)


@router.get("/market/career-graph", response_model=CareerGraphOut, response_class=JSONResponse)
async def career_graph(
    role: str = Query(..., min_length=1),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> CareerGraphOut:
    features_df = datastore.get_features_df() if datastore.is_ready else pd.DataFrame()
    transitions = _build_career_graph(features_df, role)
    return CareerGraphOut(
        role=role,
        transitions=[
            CareerTransitionOut(
                from_grade=transition["from_grade"],
                to_grade=transition["to_grade"],
                skills_to_add=transition["skills_to_add"],
                salary_delta_pct=transition["salary_delta_pct"],
                demand_trend=transition["demand_trend"],
            )
            for transition in transitions
        ],
    )


async def _history_df(request: Request, datastore: DataStore) -> pd.DataFrame:
    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is not None:
        async with session_maker() as session:
            rows = (
                await session.scalars(select(MarketSnapshot).order_by(MarketSnapshot.week_start, MarketSnapshot.id))
            ).all()
        if rows:
            return snapshots_to_frame(list(rows))
    return datastore.get_snapshot_history_df()


def _dataset_run_id(datastore: DataStore) -> str | None:
    meta = datastore.get_dataset_meta() or {}
    run_id = meta.get("run_id")
    return str(run_id) if run_id else None


def _trend_trust(datastore: DataStore) -> tuple[dict[str, Any], bool]:
    payload = dataset_trust_payload(datastore)
    product_eligibility = payload.get("product_eligibility")
    trends = product_eligibility.get("trends") if isinstance(product_eligibility, dict) else None
    trend_gate = payload.get("trend_ready_gate")
    trend_gate_ready = isinstance(trend_gate, dict) and trend_gate.get("eligible") is True
    lineage_ready = (
        payload.get("dataset_semantic_type") == "historical_publication_facts"
        and payload.get("date_semantics_status") == "passed"
    )
    trend_ready = bool(
        isinstance(trends, dict) and trends.get("eligible") is True and trend_gate_ready and lineage_ready
    )
    if trend_ready:
        payload["claim_status"] = "ready"
        payload["warnings"] = []
        return payload, True

    user_message = TREND_BLOCKED_USER_MESSAGE
    if isinstance(trends, dict) and trends.get("reason"):
        user_message = str(trends.get("user_message") or user_message)
    if isinstance(trend_gate, dict) and trend_gate.get("user_message"):
        user_message = str(trend_gate["user_message"])
    payload["claim_status"] = "blocked"
    payload["warnings"] = [user_message]
    return payload, False


def _trend_point(
    *,
    week_start: Any,
    value: float,
    dataset_run_id: str | None,
    source_row_count: int | None,
) -> TrendDataPoint:
    is_complete = _is_complete_week(week_start)
    return TrendDataPoint(
        week_start=week_start,
        value=value,
        dataset_run_id=dataset_run_id,
        coverage_window="weekly",
        completeness="complete" if is_complete else "partial",
        is_complete=is_complete,
        source_row_count=source_row_count,
        confidence=_confidence_from_rows(source_row_count),
    )


def _weekly_source_counts(history: pd.DataFrame, *, role: str, grade: str) -> dict[str, int]:
    if history.empty or "vacancy_count" not in history.columns:
        return {}
    filtered = history.copy()
    if "role" in filtered.columns:
        filtered = filtered[filtered["role"].astype(str) == role]
    if "grade" in filtered.columns:
        filtered = filtered[filtered["grade"].astype(str) == grade]
    if filtered.empty or "week_start" not in filtered.columns:
        return {}
    grouped = filtered.groupby("week_start", observed=True)["vacancy_count"].sum()
    return {_week_key(week): int(count) for week, count in grouped.items()}


def _week_key(value: Any) -> str:
    if hasattr(value, "date"):
        value = value.date()
    return str(value)


def _is_complete_week(value: Any) -> bool:
    if hasattr(value, "date"):
        value = value.date()
    if not isinstance(value, date):
        return True
    today = date.today()
    current_week = today - timedelta(days=today.weekday())
    return value < current_week


def _confidence_from_rows(row_count: int | None) -> str | None:
    if row_count is None:
        return None
    if row_count >= 100:
        return "high"
    if row_count >= 30:
        return "medium"
    return "low"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_career_graph(features_df: pd.DataFrame, role: str) -> list[dict[str, Any]]:
    try:
        from skillra_pda.career_path import build_career_graph  # type: ignore[import-not-found]

        return [
            {
                "from_grade": transition.from_node.grade,
                "to_grade": transition.to_node.grade,
                "skills_to_add": transition.skills_to_add,
                "salary_delta_pct": transition.salary_delta_pct,
                "demand_trend": transition.demand_trend,
            }
            for transition in build_career_graph(features_df, role)
        ]
    except Exception:  # noqa: BLE001
        return _fallback_career_graph(features_df, role)


def _fallback_career_graph(features_df: pd.DataFrame, role: str) -> list[dict[str, Any]]:
    if features_df.empty or "primary_role" not in features_df.columns:
        return []
    grade_col = "grade_final" if "grade_final" in features_df.columns else "grade"
    if grade_col not in features_df.columns:
        return []

    role_df = features_df[features_df["primary_role"] == role]
    grade_stats: list[dict[str, Any]] = []
    for grade in sorted(role_df[grade_col].dropna().unique(), key=_grade_sort_key):
        stats = _grade_stats(role_df, grade_col, grade)
        if stats is not None:
            grade_stats.append(stats)
    transitions: list[dict[str, Any]] = []
    for current, next_item in zip(grade_stats, grade_stats[1:]):
        current_skills = set(current["top_skills"])
        transitions.append(
            {
                "from_grade": current["grade"],
                "to_grade": next_item["grade"],
                "skills_to_add": [skill for skill in next_item["top_skills"] if skill not in current_skills][:5],
                "salary_delta_pct": _salary_delta_pct(current["salary_p50"], next_item["salary_p50"]),
                "demand_trend": "stable",
            }
        )
    return transitions


def _grade_stats(role_df: pd.DataFrame, grade_col: str, grade: Any) -> dict[str, Any] | None:
    df = role_df[role_df[grade_col] == grade]
    if df.empty:
        return None
    salary_col = _salary_col(df)
    salary_p50 = float(df[salary_col].median()) if salary_col and df[salary_col].notna().any() else None
    return {"grade": str(grade), "salary_p50": salary_p50, "top_skills": _top_skills(df)}


def _top_skills(df: pd.DataFrame) -> list[str]:
    skill_cols = [col for col in df.columns if col.startswith("skill_") or col.startswith("has_")]
    if not skill_cols:
        if "top_skills" in df.columns and not df["top_skills"].dropna().empty:
            return _skill_list(df["top_skills"].dropna().iloc[0])
        return []
    means = df[skill_cols].fillna(False).astype(bool).mean().sort_values(ascending=False)
    return [col.removeprefix("skill_").removeprefix("has_") for col, value in means.items() if value > 0][:10]


def _skill_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _salary_col(df: pd.DataFrame) -> str | None:
    for column in ("salary_mid_rub_capped", "salary_mid_rub", "salary_mid", "salary_median"):
        if column in df.columns:
            return column
    return None


def _salary_delta_pct(current: float | None, next_value: float | None) -> float | None:
    if current in (None, 0) or next_value is None:
        return None
    return round(((next_value - current) / current) * 100, 2)


def _grade_sort_key(grade: Any) -> tuple[int, str]:
    normalized = str(grade).lower()
    return (GRADE_RANK.get(normalized, 999), normalized)
