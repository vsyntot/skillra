"""Vacancy indexer: parquet → vacancy_snapshots (PostgreSQL) → MeiliSearch.

Sprint-009 TASK-01: ETL pipeline that populates the vacancy_snapshots table
and keeps MeiliSearch index in sync.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
import pandas as pd
from skillra_api.db.models import VacancySnapshot
from skillra_api.services.circuit_breaker import with_retry
from skillra_api.services.search import (
    VACANCY_FILTERABLE_ATTRIBUTES,
    VACANCY_SEARCHABLE_ATTRIBUTES,
    VACANCY_SORTABLE_ATTRIBUTES,
    SearchService,
    get_search_client,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from skillra_api.config import Settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 500  # rows per bulk-insert
DESCRIPTION_MAX_LEN = 5000
VACANCY_INDEX_UID = "vacancies"
MEILI_TASK_TIMEOUT_SECONDS = 60.0
MEILI_TASK_POLL_SECONDS = 0.2

VACANCY_SCHEMA_ALIASES: dict[str, tuple[str, ...]] = {
    "hh_vacancy_id": ("hh_vacancy_id", "vacancy_id", "id"),
    "title": ("title", "name"),
    "url": ("url", "vacancy_url", "hh_url"),
    "hh_url": ("hh_url", "vacancy_url", "url"),
    "published_at": ("published_at", "published_at_iso", "published_at_raw"),
}


def _normalize_vacancy_schema(features_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize parser/pipeline column aliases to the DB/indexer contract."""

    normalized = features_df.copy()
    for target, candidates in VACANCY_SCHEMA_ALIASES.items():
        present = [column for column in candidates if column in normalized.columns]
        if not present:
            continue
        if target not in normalized.columns:
            normalized[target] = pd.NA
        target_values = normalized[target]
        missing = target_values.isna() | target_values.astype(str).str.strip().eq("")
        for column in present:
            source_values = normalized[column]
            normalized.loc[missing, target] = source_values.loc[missing]
            target_values = normalized[target]
            missing = target_values.isna() | target_values.astype(str).str.strip().eq("")
            if not bool(missing.any()):
                break
    return normalized


def _snapshots_from_df(features_df: pd.DataFrame, *, dataset_run_id: str | None = None) -> list[VacancySnapshot]:
    """Parse parquet rows into VacancySnapshot objects."""

    features_df = _normalize_vacancy_schema(features_df)
    snapshots_by_id: dict[str, VacancySnapshot] = {}
    now = datetime.now(timezone.utc)

    required_columns = {"hh_vacancy_id", "title"}
    if not required_columns.issubset(set(features_df.columns)):
        missing = required_columns - set(features_df.columns)
        raise ValueError(f"features_df missing required columns: {missing}")

    for row in features_df.itertuples(index=False):
        hh_id = _normalize_hh_id(getattr(row, "hh_vacancy_id", None))
        title = str(getattr(row, "title", "") or "").strip()
        if not hh_id or not title:
            continue

        skills: list[str] = []
        raw_skills = getattr(row, "skills", None) or getattr(row, "top_skills_list", None)
        if isinstance(raw_skills, list):
            skills = [str(s) for s in raw_skills if s]
        elif isinstance(raw_skills, str) and raw_skills:
            skills = [s.strip() for s in raw_skills.split(",") if s.strip()]

        snapshots_by_id[hh_id] = VacancySnapshot(
            hh_vacancy_id=hh_id,
            title=title,
            primary_role=_str_or_none(getattr(row, "primary_role", None)),
            grade=_str_or_none(getattr(row, "grade_final", None) or getattr(row, "grade", None)),
            city=_str_or_none(getattr(row, "city", None)),
            city_tier=_str_or_none(getattr(row, "city_tier", None)),
            country=_str_or_none(getattr(row, "country", None)),
            region=_str_or_none(getattr(row, "region", None)),
            city_normalized=_str_or_none(getattr(row, "city_normalized", None)),
            geo_scope=_str_or_none(getattr(row, "geo_scope", None)),
            salary_from=_int_or_none(getattr(row, "salary_from", None)),
            salary_to=_int_or_none(getattr(row, "salary_to", None)),
            skills=skills,
            description_snippet=_truncate(getattr(row, "description", None), DESCRIPTION_MAX_LEN),
            url=_str_or_none(getattr(row, "url", None)),
            hh_url=_str_or_none(getattr(row, "hh_url", None) or getattr(row, "url", None)),
            published_at=_datetime_or_none(getattr(row, "published_at", None)),
            indexed_at=now,
            dataset_run_id=dataset_run_id,
        )

    return list(snapshots_by_id.values())


async def _insert_snapshots(session: AsyncSession, snapshots: list[VacancySnapshot]) -> int:
    """Insert vacancy snapshots in batches."""

    inserted = 0
    for i in range(0, len(snapshots), BATCH_SIZE):
        batch = snapshots[i : i + BATCH_SIZE]
        session.add_all(batch)
        await session.flush()
        inserted += len(batch)
    return inserted


async def _index_snapshots(settings: Settings, snapshots: list[VacancySnapshot]) -> int:
    """Publish snapshots to MeiliSearch using a verified staging index swap."""

    if not snapshots:
        return 0
    if not settings.meilisearch_url:
        return 0

    return await _replace_vacancies_index(settings, snapshots)


async def _replace_vacancies_index(settings: Settings, snapshots: list[VacancySnapshot]) -> int:
    """Build a candidate MeiliSearch index and atomically swap it into service."""

    if not settings.meilisearch_url:
        return 0

    expected = len(snapshots)
    dataset_run_id = _snapshot_dataset_run_id(snapshots)
    staging_uid = _staging_index_uid(dataset_run_id)
    headers = _meili_headers(settings.meilisearch_api_key)
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(
        base_url=settings.meilisearch_url.rstrip("/"),
        headers=headers,
        timeout=timeout,
    ) as client:
        await _delete_meili_index_if_exists(client, staging_uid)
        await _create_meili_index_if_missing(client, staging_uid)
        await _apply_vacancy_index_settings(client, staging_uid, max_total_hits=max(expected, 1000))

        documents = [SearchService._to_document(snapshot) for snapshot in snapshots]
        for i in range(0, len(documents), BATCH_SIZE):
            await _wait_meili_task(
                client,
                await _meili_request(
                    client,
                    "POST",
                    f"/indexes/{_quote_uid(staging_uid)}/documents",
                    params={"primaryKey": "id"},
                    json=documents[i : i + BATCH_SIZE],
                ),
            )

        candidate_total = await _meili_document_count(client, staging_uid)
        if candidate_total != expected:
            await _delete_meili_index_if_exists(client, staging_uid)
            raise RuntimeError(
                "MeiliSearch staging index incomplete: "
                f"expected={expected} candidate_total={candidate_total} staging_uid={staging_uid}"
            )

        await _create_meili_index_if_missing(client, VACANCY_INDEX_UID)
        await _apply_vacancy_index_settings(client, VACANCY_INDEX_UID)
        await _wait_meili_task(
            client,
            await _meili_request(
                client,
                "POST",
                "/swap-indexes",
                json=[{"indexes": [VACANCY_INDEX_UID, staging_uid]}],
            ),
        )
        await _delete_meili_index_if_exists(client, staging_uid)

    logger.info(
        "MeiliSearch vacancy index swapped from staging",
        extra={"count": expected, "staging_uid": staging_uid, "dataset_run_id": dataset_run_id},
    )
    return expected


async def _delete_indexed_snapshots(settings: Settings, vacancy_ids: list[str]) -> int:
    """Delete stale vacancy documents from MeiliSearch."""

    if not vacancy_ids:
        return 0

    client = await get_search_client(settings)
    if client is None:
        return 0
    search_service = SearchService(client=client)
    for i in range(0, len(vacancy_ids), BATCH_SIZE):
        batch = vacancy_ids[i : i + BATCH_SIZE]
        await search_service.delete_vacancies(batch)
    logger.info("MeiliSearch stale vacancies deleted", extra={"count": len(vacancy_ids)})
    return len(vacancy_ids)


async def _search_index_total(settings: Settings, dataset_run_id: str | None) -> int | None:
    """Return MeiliSearch vacancy document count for the current dataset when configured."""

    if not settings.meilisearch_url:
        return None

    headers = _meili_headers(settings.meilisearch_api_key)
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(
        base_url=settings.meilisearch_url.rstrip("/"),
        headers=headers,
        timeout=timeout,
    ) as client:
        try:
            if dataset_run_id:
                response = await _meili_request(
                    client,
                    "POST",
                    f"/indexes/{_quote_uid(VACANCY_INDEX_UID)}/search",
                    json={"q": "", "limit": 0, "filter": f'dataset_run_id = "{dataset_run_id}"'},
                )
                return _meili_search_total(response)
            return await _meili_document_count(client, VACANCY_INDEX_UID)
        except RuntimeError as exc:
            if "index_not_found" in str(exc).lower() or "not found" in str(exc).lower():
                return 0
            raise


async def _db_snapshot_total(session: AsyncSession, dataset_run_id: str | None) -> int:
    query = select(func.count()).select_from(VacancySnapshot)
    if dataset_run_id:
        query = query.where(VacancySnapshot.dataset_run_id == dataset_run_id)
    return int(await session.scalar(query) or 0)


def _completeness_status(expected: int, db_total: int, search_total: int | None) -> str:
    if db_total != expected:
        return "incomplete"
    if search_total is None:
        return "not_configured"
    return "complete" if search_total == expected else "incomplete"


def _raise_if_incomplete(result: dict[str, int | str | None]) -> None:
    if result.get("completeness_status") != "incomplete":
        return
    raise RuntimeError(
        "Vacancy index publish incomplete: "
        f"expected={result.get('expected')} db_total={result.get('db_total')} "
        f"search_total={result.get('search_total')}"
    )


@with_retry(Exception, max_attempts=3, wait_min=0.2, wait_max=2.0)
async def _index_vacancy_batch(search_service: SearchService, batch: list[VacancySnapshot]) -> None:
    await search_service.index_vacancies(batch)


async def sync_vacancy_snapshots(
    session: AsyncSession,
    features_df: pd.DataFrame,
    settings: Settings,
    *,
    truncate: bool = True,
    dataset_run_id: str | None = None,
) -> dict[str, int | str | None]:
    """Sync hh_features parquet → vacancy_snapshots → MeiliSearch.

    Returns: {"inserted": N, "indexed": N}
    """
    if truncate:
        await session.execute(delete(VacancySnapshot))
        await session.flush()

    snapshots = _snapshots_from_df(features_df, dataset_run_id=dataset_run_id)
    expected = len(snapshots)
    inserted = await _insert_snapshots(session, snapshots)
    await session.commit()
    logger.info("vacancy_snapshots inserted", extra={"count": inserted})

    indexed = await _index_snapshots(settings, snapshots)
    db_total = await _db_snapshot_total(session, dataset_run_id)
    search_total = await _search_index_total(settings, dataset_run_id)
    result: dict[str, int | str | None] = {
        "inserted": inserted,
        "indexed": indexed,
        "expected": expected,
        "db_total": db_total,
        "search_total": search_total,
        "completeness_status": _completeness_status(expected, db_total, search_total),
    }
    _raise_if_incomplete(result)

    return result


async def sync_vacancy_snapshots_incremental(
    session: AsyncSession,
    features_df: pd.DataFrame,
    settings: Settings,
    *,
    force_full: bool = False,
    dataset_run_id: str | None = None,
) -> dict[str, int | str | None]:
    """Reconcile vacancy_snapshots with the latest feature dataset."""

    features_df = _normalize_vacancy_schema(features_df)
    existing_snapshots = list((await session.scalars(select(VacancySnapshot))).all())
    existing_by_id = {snapshot.hh_vacancy_id: snapshot for snapshot in existing_snapshots}
    existing_ids = set(existing_by_id)
    if force_full or not existing_ids:
        full_result = await sync_vacancy_snapshots(session, features_df, settings, dataset_run_id=dataset_run_id)
        return {**full_result, "strategy": "full"}

    incoming_by_id = {
        snapshot.hh_vacancy_id: snapshot for snapshot in _snapshots_from_df(features_df, dataset_run_id=dataset_run_id)
    }
    incoming_ids = set(incoming_by_id)
    expected = len(incoming_by_id)
    stale_ids = sorted(existing_ids - incoming_ids)

    inserted_snapshots: list[VacancySnapshot] = []
    updated_snapshots: list[VacancySnapshot] = []
    for hh_id, incoming in incoming_by_id.items():
        existing = existing_by_id.get(hh_id)
        if existing is None:
            inserted_snapshots.append(incoming)
            continue
        if _copy_snapshot_fields(existing, incoming):
            updated_snapshots.append(existing)

    inserted = await _insert_snapshots(session, inserted_snapshots)
    if stale_ids:
        await session.execute(delete(VacancySnapshot).where(VacancySnapshot.hh_vacancy_id.in_(stale_ids)))
    await session.commit()

    indexed = await _index_snapshots(settings, list(incoming_by_id.values()))
    deindexed = len(stale_ids) if indexed else 0
    db_total = await _db_snapshot_total(session, dataset_run_id)
    search_total = await _search_index_total(settings, dataset_run_id)
    result: dict[str, int | str | None] = {
        "inserted": inserted,
        "updated": len(updated_snapshots),
        "deleted": len(stale_ids),
        "indexed": indexed,
        "deindexed": deindexed,
        "expected": expected,
        "db_total": db_total,
        "search_total": search_total,
        "completeness_status": _completeness_status(expected, db_total, search_total),
        "strategy": "reconcile",
    }
    _raise_if_incomplete(result)
    return result


def _copy_snapshot_fields(target: VacancySnapshot, source: VacancySnapshot) -> bool:
    """Copy mutable fields from source into target and return whether anything changed."""

    changed = False
    fields = (
        "title",
        "primary_role",
        "grade",
        "city",
        "city_tier",
        "country",
        "region",
        "city_normalized",
        "geo_scope",
        "salary_from",
        "salary_to",
        "skills",
        "description_snippet",
        "url",
        "hh_url",
        "published_at",
        "dataset_run_id",
    )
    for field in fields:
        source_value = getattr(source, field)
        if getattr(target, field) != source_value:
            setattr(target, field, source_value)
            changed = True
    if changed:
        target.indexed_at = source.indexed_at
    return changed


def _snapshot_dataset_run_id(snapshots: list[VacancySnapshot]) -> str | None:
    for snapshot in snapshots:
        if snapshot.dataset_run_id:
            return snapshot.dataset_run_id
    return None


def _staging_index_uid(dataset_run_id: str | None) -> str:
    source = dataset_run_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    safe = "".join(char if char.isalnum() else "_" for char in source.lower()).strip("_")
    safe = safe[:80] or "unknown"
    return f"{VACANCY_INDEX_UID}__staging__{safe}"


def _quote_uid(uid: str) -> str:
    return quote(uid, safe="")


def _meili_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def _create_meili_index_if_missing(client: httpx.AsyncClient, uid: str) -> None:
    try:
        await _meili_request(client, "GET", f"/indexes/{_quote_uid(uid)}")
        return
    except RuntimeError as exc:
        if "index_not_found" not in str(exc).lower() and "not found" not in str(exc).lower():
            raise

    await _wait_meili_task(
        client,
        await _meili_request(client, "POST", "/indexes", json={"uid": uid, "primaryKey": "id"}),
    )


async def _delete_meili_index_if_exists(client: httpx.AsyncClient, uid: str) -> None:
    try:
        await _wait_meili_task(
            client,
            await _meili_request(client, "DELETE", f"/indexes/{_quote_uid(uid)}"),
        )
    except RuntimeError as exc:
        if "index_not_found" not in str(exc).lower() and "not found" not in str(exc).lower():
            raise


async def _apply_vacancy_index_settings(
    client: httpx.AsyncClient,
    uid: str,
    *,
    max_total_hits: int | None = None,
) -> None:
    settings: dict[str, Any] = {
        "searchableAttributes": VACANCY_SEARCHABLE_ATTRIBUTES,
        "filterableAttributes": VACANCY_FILTERABLE_ATTRIBUTES,
        "sortableAttributes": VACANCY_SORTABLE_ATTRIBUTES,
    }
    if max_total_hits is not None:
        settings["pagination"] = {"maxTotalHits": max_total_hits}

    await _wait_meili_task(
        client,
        await _meili_request(
            client,
            "PATCH",
            f"/indexes/{_quote_uid(uid)}/settings",
            json=settings,
        ),
    )


async def _meili_document_count(client: httpx.AsyncClient, uid: str) -> int:
    response = await _meili_request(client, "GET", f"/indexes/{_quote_uid(uid)}/stats")
    value = response.get("numberOfDocuments")
    return int(value or 0)


async def _wait_meili_task(client: httpx.AsyncClient, task: dict[str, Any] | None) -> None:
    task_uid = _meili_task_uid(task)
    if task_uid is None:
        return

    deadline = datetime.now(timezone.utc).timestamp() + MEILI_TASK_TIMEOUT_SECONDS
    while True:
        response = await _meili_request(client, "GET", f"/tasks/{task_uid}")
        status = str(response.get("status") or "").lower()
        if status in {"succeeded", "success"}:
            return
        if status in {"failed", "canceled", "cancelled"}:
            raise RuntimeError(f"MeiliSearch task {task_uid} ended with status {status}: {response}")
        if datetime.now(timezone.utc).timestamp() > deadline:
            raise RuntimeError(f"MeiliSearch task {task_uid} did not finish in {MEILI_TASK_TIMEOUT_SECONDS:g}s")

        await asyncio.sleep(MEILI_TASK_POLL_SECONDS)


async def _meili_request(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.request(method, path, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        error_code = payload.get("code") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else response.text
        raise RuntimeError(f"MeiliSearch {method} {path} failed: HTTP {response.status_code} {error_code} {message}")
    return payload if isinstance(payload, dict) else {}


def _meili_task_uid(task: dict[str, Any] | None) -> int | str | None:
    if not task:
        return None
    return task.get("taskUid") or task.get("task_uid") or task.get("uid")


def _meili_search_total(payload: dict[str, Any]) -> int:
    for key in ("estimatedTotalHits", "totalHits", "estimated_total_hits", "total_hits"):
        value = payload.get(key)
        if value is not None:
            return int(value)
    hits = payload.get("hits")
    return len(hits) if isinstance(hits, list) else 0


def _str_or_none(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


def _normalize_hh_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _truncate(value: Any, max_len: int) -> str | None:
    s = _str_or_none(value)
    return s[:max_len] if s else None


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize(timezone.utc)
        else:
            ts = ts.tz_convert(timezone.utc)
        return ts.to_pydatetime()
    except Exception:  # noqa: BLE001
        return None
