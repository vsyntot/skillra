from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from skillra_api.datastore import DataStore, DataUnavailableError
from skillra_api.deps import get_datastore_dependency, get_redis_dependency
from skillra_api.deps.auth import require_user_or_service_token
from skillra_api.schemas import (
    DatasetMetaResponse,
    MetaCitiesResponse,
    MetaCityTiersResponse,
    MetaCountriesResponse,
    MetaDomainsResponse,
    MetaGeoScopesResponse,
    MetaGradesResponse,
    MetaRegionsResponse,
    MetaRolesResponse,
    MetaWorkModesResponse,
    PaginatedMetaSkillsResponse,
)
from skillra_api.services.analytics import _grade_column
from skillra_api.services.meta_cache import cached_meta
from skillra_api.services.responses import data_unavailable_error

router = APIRouter(
    prefix="/v1/meta",
    tags=["meta"],
    dependencies=[Depends(require_user_or_service_token)],
)


def _unique_sorted_values(values: list[Any]) -> list[str]:
    return sorted({str(value) for value in values if value is not None})


def _column_values(df: Any, column: str) -> list[Any]:
    if column not in df.columns:
        return []
    return df[column].dropna().unique().tolist()


# ---------------------------------------------------------------------------
# Sync compute helpers — run via asyncio.to_thread to avoid blocking the event
# loop with pandas operations (see ADR-002 / GAP-04).
# ---------------------------------------------------------------------------


def _compute_roles(market_view_df: pd.DataFrame) -> list[str]:
    return _unique_sorted_values(_column_values(market_view_df, "primary_role"))


def _compute_grades(market_view_df: pd.DataFrame) -> list[str]:
    grade_column = _grade_column(market_view_df)
    if not grade_column:
        return []
    return _unique_sorted_values(_column_values(market_view_df, grade_column))


def _compute_city_tiers(market_view_df: pd.DataFrame) -> list[str]:
    return _unique_sorted_values(_column_values(market_view_df, "city_tier"))


def _compute_countries(market_view_df: pd.DataFrame) -> list[str]:
    return _unique_sorted_values(_column_values(market_view_df, "country"))


def _compute_regions(market_view_df: pd.DataFrame) -> list[str]:
    return _unique_sorted_values(_column_values(market_view_df, "region"))


def _compute_cities(market_view_df: pd.DataFrame) -> list[str]:
    return _unique_sorted_values(_column_values(market_view_df, "city_normalized"))


def _compute_geo_scopes(features_df: pd.DataFrame) -> list[str]:
    return _unique_sorted_values(_column_values(features_df, "geo_scope"))


def _compute_work_modes(features_df: pd.DataFrame) -> list[str]:
    return _unique_sorted_values(_column_values(features_df, "work_mode"))


def _compute_domains(market_view_df: pd.DataFrame) -> list[str]:
    if "domain" not in market_view_df.columns:
        return []
    return _unique_sorted_values(_column_values(market_view_df, "domain"))


def _compute_skills(features_df: pd.DataFrame) -> list[str]:
    skill_columns = [col for col in features_df.columns if col.startswith("skill_") or col.startswith("has_")]
    return sorted({col.removeprefix("skill_").removeprefix("has_") for col in skill_columns})


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def list_roles(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaRolesResponse | JSONResponse:
    """Return available roles sourced from the market view."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    roles = await cached_meta(
        redis,
        "roles",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "roles", _compute_roles, market_view_df),
    )
    return MetaRolesResponse(roles=roles)


async def list_grades(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaGradesResponse | JSONResponse:
    """Return available grades sourced from the market view."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    grades = await cached_meta(
        redis,
        "grades",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "grades", _compute_grades, market_view_df),
    )
    return MetaGradesResponse(grades=grades)


async def list_city_tiers(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaCityTiersResponse | JSONResponse:
    """Return available city tiers sourced from the market view."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    city_tiers = await cached_meta(
        redis,
        "city-tiers",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "city_tiers", _compute_city_tiers, market_view_df),
    )
    return MetaCityTiersResponse(city_tiers=city_tiers)


async def list_countries(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaCountriesResponse | JSONResponse:
    """Return available countries sourced from the market view."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    countries = await cached_meta(
        redis,
        "countries",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "countries", _compute_countries, market_view_df),
    )
    return MetaCountriesResponse(countries=countries)


async def list_regions(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaRegionsResponse | JSONResponse:
    """Return available regions sourced from the market view."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    regions = await cached_meta(
        redis,
        "regions",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "regions", _compute_regions, market_view_df),
    )
    return MetaRegionsResponse(regions=regions)


async def list_cities(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaCitiesResponse | JSONResponse:
    """Return available normalized cities sourced from the market view."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    cities = await cached_meta(
        redis,
        "cities",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "cities", _compute_cities, market_view_df),
    )
    return MetaCitiesResponse(cities=cities)


async def list_work_modes(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaWorkModesResponse | JSONResponse:
    """Return available work modes sourced from the features dataset."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    work_modes = await cached_meta(
        redis,
        "work-modes",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "work_modes", _compute_work_modes, features_df),
    )
    return MetaWorkModesResponse(work_modes=work_modes)


async def list_geo_scopes(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaGeoScopesResponse | JSONResponse:
    """Return available geography scopes sourced from the features dataset."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    geo_scopes = await cached_meta(
        redis,
        "geo-scopes",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "geo_scopes", _compute_geo_scopes, features_df),
    )
    return MetaGeoScopesResponse(geo_scopes=geo_scopes)


async def list_domains(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> MetaDomainsResponse | JSONResponse:
    """Return available domains sourced from the market view when present."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        market_view_df = datastore.get_market_view_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    domains = await cached_meta(
        redis,
        "domains",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "domains", _compute_domains, market_view_df),
    )
    return MetaDomainsResponse(domains=domains)


async def list_skills(
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
    limit: int = Query(100, ge=1, le=500, description="Max skills to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    search: str | None = Query(None, max_length=100, description="Case-insensitive substring filter"),
) -> PaginatedMetaSkillsResponse | JSONResponse:
    """Return available skills sourced from skill_* and has_* columns with pagination."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    all_skills: list[str] = await cached_meta(
        redis,
        "skills",
        lambda: asyncio.to_thread(datastore.get_cached_meta, "skills", _compute_skills, features_df),
    )

    if search:
        search_lower = search.lower()
        all_skills = [s for s in all_skills if search_lower in s.lower()]

    total = len(all_skills)
    page_skills = all_skills[offset : offset + limit]
    return PaginatedMetaSkillsResponse(skills=page_skills, total=total, limit=limit, offset=offset)


async def dataset_meta(datastore: DataStore = Depends(get_datastore_dependency)) -> DatasetMetaResponse | JSONResponse:
    """Return dataset metadata describing the loaded parquet artefacts."""

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    raw = datastore.get_dataset_meta() or {}
    return DatasetMetaResponse(**raw)


router.add_api_route(
    "/roles",
    list_roles,
    response_model=MetaRolesResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/grades",
    list_grades,
    response_model=MetaGradesResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/city-tiers",
    list_city_tiers,
    response_model=MetaCityTiersResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/countries",
    list_countries,
    response_model=MetaCountriesResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/regions",
    list_regions,
    response_model=MetaRegionsResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/cities",
    list_cities,
    response_model=MetaCitiesResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/work-modes",
    list_work_modes,
    response_model=MetaWorkModesResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/geo-scopes",
    list_geo_scopes,
    response_model=MetaGeoScopesResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/domains",
    list_domains,
    response_model=MetaDomainsResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/skills",
    list_skills,
    response_model=PaginatedMetaSkillsResponse,
    response_class=JSONResponse,
    methods=["GET"],
)
router.add_api_route(
    "/dataset",
    dataset_meta,
    response_class=JSONResponse,
    response_model=DatasetMetaResponse,
    response_model_exclude_none=True,
    methods=["GET"],
)
