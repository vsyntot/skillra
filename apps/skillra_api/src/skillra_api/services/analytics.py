"""Analytics service layer: segment summary and persona analysis.

This module contains the shared business logic used by both API routers
(market, persona, digest) and the digest_builder service.

Keeping business logic here prevents architectural inversion (services → routers)
and enables independent testing without starting the full FastAPI application.
See GAP-N01 / SPRINT-003.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from importlib.resources import files
from typing import Any, Iterable, Mapping

import pandas as pd
import yaml
from fastapi.responses import JSONResponse
from skillra_api.datastore import DataStore, DataUnavailableError
from skillra_api.schemas import (
    MarketSummary,
    PersonaAnalysisResponse,
    PersonaProfile,
    SegmentFilters,
    SegmentSummary,
    SkillResource,
)
from skillra_api.services.responses import data_unavailable_error, invalid_skills_error
from skillra_api.services.trust import dataset_trust_payload

from skillra_pda.market import market_confidence
from skillra_pda.personas import Persona, analyze_persona

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_skill_resources() -> dict[str, list[SkillResource]]:
    """Load static learning resources keyed by canonical skill name."""

    try:
        resource_path = files("skillra_pda").joinpath("skill_resources.yaml")
        payload = yaml.safe_load(resource_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load skill learning resources")
        return {}

    resources: dict[str, list[SkillResource]] = {}
    for raw_skill, raw_items in payload.items():
        if not isinstance(raw_items, list):
            continue
        items: list[SkillResource] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            try:
                items.append(SkillResource(**raw_item))
            except Exception:  # noqa: BLE001
                logger.warning("Invalid skill resource ignored", extra={"skill": raw_skill})
        if items:
            resources[_normalize_skill_name(str(raw_skill))] = items
    return resources


def _resources_for_skills(skills: Iterable[str]) -> dict[str, list[SkillResource]]:
    resources = _load_skill_resources()
    return {skill: resources[skill] for skill in skills if skill in resources}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _grade_column(df: pd.DataFrame) -> str | None:
    """Return the grade column name present in *df*, or None."""
    if "grade_final" in df.columns:
        return "grade_final"
    if "grade" in df.columns:
        return "grade"
    return None


# ---------------------------------------------------------------------------
# Segment summary — compute helpers (CPU-bound, must run in thread pool)
# ---------------------------------------------------------------------------


def _apply_filter(df: pd.DataFrame, column: str | None, value: str | None) -> pd.DataFrame:
    if not value or not column or column not in df.columns:
        return df
    return df[df[column] == value]


def _apply_geo_filters(df: pd.DataFrame, filters: SegmentFilters) -> pd.DataFrame:
    filtered = df
    filtered = _apply_filter(filtered, "country", filters.country)
    filtered = _apply_filter(filtered, "region", filters.region)
    filtered = _apply_filter(filtered, "city_normalized", filters.city)
    filtered = _apply_filter(filtered, "geo_scope", filters.geo_scope)
    return filtered


def _geo_scope_label(df: pd.DataFrame, requested_scope: str | None = None) -> str | None:
    if requested_scope:
        return requested_scope
    if "geo_scope" not in df.columns:
        return None
    scopes = df["geo_scope"].dropna().astype(str)
    unique_scopes = sorted({scope for scope in scopes if scope and scope != "unknown"})
    if len(unique_scopes) == 1:
        return unique_scopes[0]
    if len(unique_scopes) > 1:
        return "mixed"
    return None


def _mean_or_none(series: pd.Series) -> float | None:
    if series.empty:
        return None
    return float(series.mean())


def _sum_int_or_none(df: pd.DataFrame, column: str) -> int | None:
    if column not in df.columns:
        return None
    return int(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _salary_coverage(vacancy_count: int, salary_sample_size: int | None) -> float | None:
    if vacancy_count <= 0:
        return None
    return round(float(salary_sample_size or 0) / vacancy_count, 6)


def _append_confidence_warning(warnings: list[str], confidence: str | None) -> None:
    if confidence == "low":
        warnings.append("Segment confidence is low; salary and demand metrics may be unstable.")


def _normalize_top_skills(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        comma_split = [part.strip() for part in value.split(",") if part.strip()]
        if comma_split:
            return comma_split
        space_split = [part.strip("[]'\"") for part in value.split() if part.strip("[]'\"")]
        return space_split or None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        return [str(skill) for skill in value if str(skill).strip()]
    value_str = str(value).strip()
    return [value_str] if value_str else None


def _compute_segment_summary(
    market_view_df: pd.DataFrame,
    features_df: pd.DataFrame,
    filters: SegmentFilters,
) -> SegmentSummary:
    """Compute segment summary from pre-loaded DataFrames (CPU-bound, runs in thread pool)."""

    grade_column_market = _grade_column(market_view_df)
    filtered_market = market_view_df.copy()
    filtered_market = _apply_filter(filtered_market, "primary_role", filters.role)
    filtered_market = _apply_filter(filtered_market, grade_column_market, filters.grade)
    filtered_market = _apply_filter(filtered_market, "city_tier", filters.city_tier)
    filtered_market = _apply_geo_filters(filtered_market, filters)
    filtered_market = _apply_filter(filtered_market, "domain", filters.domain)

    warnings: list[str] = []

    # Validate filter values against available dataset values (C-GAP-04)
    if filters.role and "primary_role" in market_view_df.columns:
        available_roles = set(market_view_df["primary_role"].dropna().unique().tolist())
        if available_roles and filters.role not in available_roles:
            warnings.append(f"Role '{filters.role}' not found in dataset. " f"Available: {sorted(available_roles)[:5]}")
    if filters.grade and grade_column_market:
        available_grades = set(market_view_df[grade_column_market].dropna().unique().tolist())
        if available_grades and filters.grade not in available_grades:
            warnings.append(f"Grade '{filters.grade}' not found in dataset. " f"Available: {sorted(available_grades)}")
    if filters.domain and "domain" in market_view_df.columns:
        available_domains = set(market_view_df["domain"].dropna().unique().tolist())
        if available_domains and filters.domain not in available_domains:
            warnings.append(
                f"Domain '{filters.domain}' not found in dataset. " f"Available: {sorted(available_domains)[:5]}"
            )

    if filters.work_mode:
        grade_column_features = _grade_column(features_df)
        filtered_features = _apply_filter(features_df, "work_mode", filters.work_mode)
        filtered_features = _apply_filter(filtered_features, "primary_role", filters.role)
        filtered_features = _apply_filter(filtered_features, grade_column_features, filters.grade)
        filtered_features = _apply_filter(filtered_features, "city_tier", filters.city_tier)
        filtered_features = _apply_geo_filters(filtered_features, filters)
        filtered_features = _apply_filter(filtered_features, "domain", filters.domain)

        if filtered_features.empty:
            warnings.append("Segment is empty for the provided filters.")
            return SegmentSummary(vacancy_count=0, warnings=warnings)

        sample_size = len(filtered_features)
        if sample_size < 5:
            warnings.append("Segment sample is small; metrics may be unstable.")

        salary_column = next(
            (
                col
                for col in ["salary_mid_rub_capped", "salary_mid_rub", "salary_mid"]
                if col in filtered_features.columns
            ),
            None,
        )

        salary_series = filtered_features[salary_column].dropna() if salary_column else pd.Series(dtype=float)
        salary_median = float(salary_series.quantile(0.5)) if not salary_series.empty else None
        salary_q25 = float(salary_series.quantile(0.25)) if not salary_series.empty else None
        salary_q75 = float(salary_series.quantile(0.75)) if not salary_series.empty else None

        vacancy_count = int(sample_size)
        salary_sample_size = int(len(salary_series))
        salary_coverage_share = _salary_coverage(vacancy_count, salary_sample_size)
        confidence = market_confidence(vacancy_count, salary_sample_size, salary_coverage_share)
        _append_confidence_warning(warnings, confidence)

        junior_friendly_share = (
            float(filtered_features["is_junior_friendly"].mean())
            if "is_junior_friendly" in filtered_features.columns
            else None
        )
        remote_share = None
        if "work_mode" in filtered_features.columns:
            remote_share = float((filtered_features["work_mode"] == "remote").mean())
        elif "is_remote" in filtered_features.columns:
            remote_share = float(filtered_features["is_remote"].mean())

        median_tech_stack_size = (
            float(filtered_features["tech_stack_size"].median())
            if "tech_stack_size" in filtered_features.columns
            else None
        )

        top_skills: list[str] | None = None
        if "top_skills" in filtered_market.columns:
            top_skills_series = filtered_market["top_skills"].dropna()
            if not top_skills_series.empty:
                top_skills = _normalize_top_skills(top_skills_series.iloc[0])

        return SegmentSummary(
            vacancy_count=vacancy_count,
            sample_size=vacancy_count,
            salary_sample_size=salary_sample_size,
            salary_coverage_share=salary_coverage_share,
            confidence=confidence,
            salary_median=salary_median,
            salary_q25=salary_q25,
            salary_q75=salary_q75,
            junior_friendly_share=junior_friendly_share,
            remote_share=remote_share,
            geo_scope=_geo_scope_label(filtered_features, filters.geo_scope),
            median_tech_stack_size=median_tech_stack_size,
            top_skills=top_skills,
            warnings=warnings,
        )

    if filtered_market.empty:
        warnings.append("Segment is empty for the provided filters.")
        return SegmentSummary(vacancy_count=0, warnings=warnings)

    vacancy_count = int(filtered_market["vacancy_count"].sum()) if "vacancy_count" in filtered_market else 0
    salary_sample_size = _sum_int_or_none(filtered_market, "salary_sample_size")
    if salary_sample_size is None:
        salary_sample_size = _sum_int_or_none(filtered_market, "vacancy_count_salary")
    salary_coverage_share = _salary_coverage(vacancy_count, salary_sample_size)
    confidence = market_confidence(vacancy_count, salary_sample_size, salary_coverage_share)
    _append_confidence_warning(warnings, confidence)
    salary_median = _mean_or_none(filtered_market["salary_median"]) if "salary_median" in filtered_market else None
    salary_q25 = _mean_or_none(filtered_market["salary_q25"]) if "salary_q25" in filtered_market else None
    salary_q75 = _mean_or_none(filtered_market["salary_q75"]) if "salary_q75" in filtered_market else None
    junior_friendly_share = (
        _mean_or_none(filtered_market["junior_friendly_share"]) if "junior_friendly_share" in filtered_market else None
    )
    remote_share = _mean_or_none(filtered_market["remote_share"]) if "remote_share" in filtered_market else None
    median_tech_stack_size = (
        _mean_or_none(filtered_market["median_tech_stack_size"])
        if "median_tech_stack_size" in filtered_market
        else None
    )

    top_skills = None
    if "top_skills" in filtered_market.columns:
        top_skills_series = filtered_market["top_skills"].dropna()
        if not top_skills_series.empty:
            top_skills = _normalize_top_skills(top_skills_series.iloc[0])

    return SegmentSummary(
        vacancy_count=vacancy_count,
        sample_size=vacancy_count,
        salary_sample_size=salary_sample_size,
        salary_coverage_share=salary_coverage_share,
        confidence=confidence,
        salary_median=salary_median,
        salary_q25=salary_q25,
        salary_q75=salary_q75,
        junior_friendly_share=junior_friendly_share,
        remote_share=remote_share,
        geo_scope=_geo_scope_label(filtered_market, filters.geo_scope),
        median_tech_stack_size=median_tech_stack_size,
        top_skills=top_skills,
        warnings=warnings,
    )


async def compute_segment_summary(datastore: DataStore, filters: SegmentFilters) -> SegmentSummary | JSONResponse:
    """Service-level async wrapper for segment summary computation.

    Checks datastore availability, fetches DataFrames and offloads the
    CPU-bound pandas computation to the thread pool via :func:`asyncio.to_thread`.
    """

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    return await asyncio.to_thread(_compute_segment_summary, market_view_df, features_df, filters)


# ---------------------------------------------------------------------------
# Persona analysis — helpers (CPU-bound, must run in thread pool)
# ---------------------------------------------------------------------------


def _normalize_skill_name(skill: str) -> str:
    normalized = skill.strip().lower()
    for prefix in ("skill_", "has_"):
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix)
    return normalized


def _skill_column_mapping(df: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for prefix in ("skill_", "has_"):
        for col in df.columns:
            if not col.startswith(prefix):
                continue
            canonical = col.removeprefix(prefix)
            current = mapping.get(canonical)
            if current is None or (current.startswith("has_") and prefix == "skill_"):
                mapping[canonical] = col
    return mapping


def _normalize_skill_list(
    skills: Iterable[str],
    mapping: Mapping[str, str],
) -> tuple[list[str], list[str]]:
    normalized: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        canonical = _normalize_skill_name(skill)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        if canonical not in mapping:
            invalid.append(skill)
            continue
        normalized.append(canonical)
    return normalized, invalid


def _skill_to_raw(skill: str, mapping: Mapping[str, str]) -> str:
    return mapping[skill]


def _serialize_demand(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    records: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        raw_name = str(row.get("skill_name"))
        canonical_name = _normalize_skill_name(raw_name)
        record = {
            "skill_name": canonical_name,
            "market_share": float(row.get("market_share", 0.0)),
            "persona_has": bool(row.get("persona_has")) if "persona_has" in row else None,
            "gap": bool(row.get("gap")) if "gap" in row else None,
        }
        if canonical_name != raw_name:
            record["skill_name_raw"] = raw_name
        records.append(record)
    return records


def _prepare_persona(
    profile: PersonaProfile, features_df: pd.DataFrame, min_market_n: int | None = None
) -> tuple[Persona | None, JSONResponse | None, dict[str, str]]:
    mapping = _skill_column_mapping(features_df)
    normalized_skills, invalid_skills = _normalize_skill_list(profile.current_skills, mapping)
    normalized_whitelist, invalid_whitelist = _normalize_skill_list(profile.skill_whitelist or [], mapping)

    invalid = invalid_skills + invalid_whitelist
    if invalid:
        return None, invalid_skills_error(invalid), mapping

    persona_payload = profile.model_dump()
    persona_payload["current_skills"] = [_skill_to_raw(skill, mapping) for skill in normalized_skills]
    if min_market_n is not None:
        persona_payload["min_market_n"] = min_market_n
    if profile.skill_whitelist is not None:
        persona_payload["skill_whitelist"] = [_skill_to_raw(skill, mapping) for skill in normalized_whitelist]

    return Persona(**persona_payload), None, mapping


def _run_persona_analysis(features_df: pd.DataFrame, persona: Persona) -> dict[str, Any]:
    """Execute analyze_persona in the thread pool (CPU-bound)."""
    return analyze_persona(features_df, persona)


async def compute_persona_analysis(
    datastore: DataStore, profile: PersonaProfile, min_market_n: int | None = None
) -> PersonaAnalysisResponse | JSONResponse:
    """Service-level async wrapper for persona analysis.

    Checks datastore availability, constructs the Persona object,
    and offloads CPU-bound :func:`analyze_persona` to the thread pool.
    """

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    persona, error_response, _ = _prepare_persona(profile, features_df, min_market_n=min_market_n)
    if error_response:
        return error_response
    assert persona is not None  # noqa: S101 — mypy guard: _prepare_persona guarantees non-None when error_response is None

    analysis = await asyncio.to_thread(_run_persona_analysis, features_df, persona)

    demand_records = [
        {
            "skill_name": rec["skill_name"],
            "market_share": rec["market_share"],
            "skill_name_raw": rec.get("skill_name_raw"),
        }
        for rec in _serialize_demand(analysis["top_skill_demand"])
        if rec.get("skill_name") is not None and rec.get("market_share") is not None
    ]

    gap_records = [
        {
            "skill_name": rec["skill_name"],
            "market_share": rec["market_share"],
            "persona_has": bool(rec.get("persona_has")),
            "gap": bool(rec.get("gap")),
            "skill_name_raw": rec.get("skill_name_raw"),
        }
        for rec in _serialize_demand(analysis["skill_gap"])
        if rec.get("skill_name") is not None and rec.get("market_share") is not None
    ]

    recommended_raw = analysis.get("recommended_skills", [])
    recommended_skills: list[str] = []
    seen_recommended: set[str] = set()
    for name in recommended_raw:
        canonical = _normalize_skill_name(name)
        if canonical in seen_recommended:
            continue
        seen_recommended.add(canonical)
        recommended_skills.append(canonical)

    market_summary = analysis.get("market_summary", {})
    summary_payload: dict[str, Any] = {
        "vacancy_count": int(market_summary.get("vacancy_count", 0)),
        "sample_size": market_summary.get("sample_size"),
        "salary_sample_size": market_summary.get("salary_sample_size"),
        "salary_coverage_share": market_summary.get("salary_coverage_share"),
        "confidence": market_summary.get("confidence"),
        "min_market_n": market_summary.get("min_market_n"),
        "salary_median": market_summary.get("salary_median"),
        "salary_q25": market_summary.get("salary_q25"),
        "salary_q75": market_summary.get("salary_q75"),
        "remote_share": market_summary.get("remote_share"),
        "geo_scope": market_summary.get("geo_scope"),
        "junior_friendly_share": market_summary.get("junior_friendly_share"),
        "top_skills": market_summary.get("top_skills"),
    }
    trust_payload = dataset_trust_payload(
        datastore,
        sample_size=summary_payload.get("sample_size") or summary_payload.get("vacancy_count"),
        confidence=summary_payload.get("confidence"),
    )
    summary_payload.update(trust_payload)

    return PersonaAnalysisResponse(
        **trust_payload,
        market_summary=MarketSummary(**summary_payload),
        recommended_skills=recommended_skills,
        top_skill_demand=demand_records,
        skill_gap=gap_records,
        warnings=analysis.get("warnings", []),
        filters_used=analysis.get("filters_used", {}),
        skill_resources=_resources_for_skills(recommended_skills),
    )
