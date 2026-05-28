"""MeiliSearch integration for vacancy and skill search."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from skillra_api.db.models import VacancySnapshot

if TYPE_CHECKING:
    from skillra_api.config import Settings

_search_client: Any | None = None
_search_client_signature: tuple[str, str | None] | None = None

VACANCY_SEARCHABLE_ATTRIBUTES = [
    "title",
    "description_snippet",
    "skills",
    "primary_role",
    "grade",
    "city",
    "city_normalized",
    "country",
    "region",
]
VACANCY_FILTERABLE_ATTRIBUTES = [
    "primary_role",
    "grade",
    "city_tier",
    "country",
    "region",
    "city_normalized",
    "geo_scope",
    "skills",
    "dataset_run_id",
]
VACANCY_SORTABLE_ATTRIBUTES = [
    "published_at",
    "indexed_at",
    "salary_from",
    "salary_to",
]
SKILL_SEARCHABLE_ATTRIBUTES = ["name", "skill"]


async def get_search_client(settings: Settings) -> Any | None:
    """Return a process-wide MeiliSearch async client, or None when disabled."""

    global _search_client, _search_client_signature

    if not settings.meilisearch_url:
        return None

    signature = (settings.meilisearch_url, settings.meilisearch_api_key or None)
    if _search_client is not None and _search_client_signature == signature:
        return _search_client

    if _search_client is not None:
        await close_search_client()

    from meilisearch_python_sdk import AsyncClient  # type: ignore[import-untyped]

    _search_client = AsyncClient(settings.meilisearch_url, settings.meilisearch_api_key or None)
    _search_client_signature = signature
    return _search_client


async def configure_search_indexes(client: Any) -> None:
    """Apply index settings required by API filters and full-text search."""

    vacancies = await client.get_index("vacancies")
    skills = await client.get_index("skills")

    await _update_index_attributes(
        vacancies,
        client=client,
        searchable=VACANCY_SEARCHABLE_ATTRIBUTES,
        filterable=VACANCY_FILTERABLE_ATTRIBUTES,
        sortable=VACANCY_SORTABLE_ATTRIBUTES,
    )
    await _update_index_attributes(skills, client=client, searchable=SKILL_SEARCHABLE_ATTRIBUTES)


async def close_search_client() -> None:
    """Close the process-wide MeiliSearch async client."""

    global _search_client, _search_client_signature

    if _search_client is not None:
        await _search_client.aclose()
    _search_client = None
    _search_client_signature = None


async def _call_if_present(target: Any, method_name: str, payload: Any, *, client: Any | None = None) -> None:
    method = getattr(target, method_name, None)
    if method is None:
        return
    result = method(payload)
    if hasattr(result, "__await__"):
        result = await result
    await _wait_for_task(client, result)


async def _update_index_attributes(
    index: Any,
    *,
    client: Any | None = None,
    searchable: list[str] | None = None,
    filterable: list[str] | None = None,
    sortable: list[str] | None = None,
) -> None:
    if searchable is not None:
        await _call_if_present(index, "update_searchable_attributes", searchable, client=client)
    if filterable is not None:
        await _call_if_present(index, "update_filterable_attributes", filterable, client=client)
    if sortable is not None:
        await _call_if_present(index, "update_sortable_attributes", sortable, client=client)


async def _wait_for_task(client: Any | None, task: Any) -> None:
    if client is None or task is None:
        return
    wait_for_task = getattr(client, "wait_for_task", None)
    if wait_for_task is None:
        return
    task_uid = _task_uid(task)
    if task_uid is None:
        return
    result = wait_for_task(task_uid)
    if hasattr(result, "__await__"):
        result = await result
    status = _task_status(result)
    if status in {"failed", "canceled", "cancelled"}:
        raise RuntimeError(f"MeiliSearch task {task_uid} ended with status {status}: {result}")


def _task_uid(task: Any) -> int | str | None:
    if isinstance(task, dict):
        return task.get("taskUid") or task.get("task_uid") or task.get("uid")
    for attr in ("task_uid", "taskUid", "uid"):
        value = getattr(task, attr, None)
        if value is not None:
            return value
    return None


def _task_status(task: Any) -> str | None:
    if isinstance(task, dict):
        status = task.get("status")
    else:
        status = getattr(task, "status", None)
    return str(status).lower() if status is not None else None


class SearchService:
    """Small async wrapper around the MeiliSearch Python SDK."""

    def __init__(self, url: str | None = None, api_key: str | None = None, *, client: Any | None = None) -> None:
        if client is None:
            from meilisearch_python_sdk import AsyncClient  # type: ignore[import-untyped]

            if not url:
                raise ValueError("MeiliSearch URL is required")
            client = AsyncClient(url, api_key or None)
            self._owns_client = True
        else:
            self._owns_client = False
        self._client = client

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def index_vacancies(self, snapshots: list[VacancySnapshot]) -> None:
        index = await self._get_or_create_index("vacancies", primary_key="id")
        task = index.add_documents([self._to_document(snapshot) for snapshot in snapshots])
        if hasattr(task, "__await__"):
            task = await task
        await _wait_for_task(self._client, task)

    async def delete_vacancies(self, vacancy_ids: list[str]) -> None:
        index = await self._get_or_create_index("vacancies", primary_key="id")
        task = index.delete_documents(vacancy_ids)
        if hasattr(task, "__await__"):
            task = await task
        await _wait_for_task(self._client, task)

    async def search_vacancies(
        self,
        query: str,
        *,
        role: str | None = None,
        grade: str | None = None,
        country: str | None = None,
        region: str | None = None,
        city: str | None = None,
        geo_scope: str | None = None,
        skill: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Any:
        index = await self._get_or_create_index("vacancies", primary_key="id")
        return await index.search(
            query,
            limit=limit,
            offset=offset,
            filter=self._build_filter(
                {
                    "primary_role": role,
                    "grade": grade,
                    "country": country,
                    "region": region,
                    "city_normalized": city,
                    "geo_scope": geo_scope,
                    "skills": skill,
                }
            ),
        )

    async def search_skills(self, query: str, *, limit: int = 10) -> Any:
        index = await self._client.get_index("skills")
        return await index.search(query, limit=limit)

    async def count_vacancies(self, *, dataset_run_id: str | None = None) -> int:
        index = await self._get_or_create_index("vacancies", primary_key="id")
        result = await index.search(
            "",
            limit=0,
            filter=self._build_filter({"dataset_run_id": dataset_run_id}),
        )
        return _search_result_total(result)

    async def _get_or_create_index(self, name: str, *, primary_key: str) -> Any:
        created = False
        try:
            index = await self._client.get_index(name)
        except Exception as exc:
            if not _is_index_not_found(exc):
                raise

            create_if_missing = getattr(self._client, "create_index_if_not_exists", None)
            if create_if_missing is not None:
                result = create_if_missing(name, primary_key=primary_key)
                if hasattr(result, "__await__"):
                    result = await result
                await _wait_for_task(self._client, result)
            else:
                create_index = getattr(self._client, "create_index")
                try:
                    result = create_index(name, primary_key=primary_key)
                except TypeError:
                    result = create_index(name, {"primaryKey": primary_key})
                if hasattr(result, "__await__"):
                    result = await result
                await _wait_for_task(self._client, result)
            created = True
            index = await self._client.get_index(name)

        if name == "vacancies":
            await _update_index_attributes(
                index,
                client=self._client,
                searchable=VACANCY_SEARCHABLE_ATTRIBUTES,
                filterable=VACANCY_FILTERABLE_ATTRIBUTES,
                sortable=VACANCY_SORTABLE_ATTRIBUTES,
            )
        elif created and name == "skills":
            await _update_index_attributes(index, client=self._client, searchable=SKILL_SEARCHABLE_ATTRIBUTES)
        return index

    @staticmethod
    def _build_filter(filters: dict[str, str | None]) -> str | None:
        clauses = [f'{field} = "{value}"' for field, value in filters.items() if value]
        return " AND ".join(clauses) if clauses else None

    @staticmethod
    def _to_document(snapshot: VacancySnapshot) -> dict[str, Any]:
        published_at = snapshot.published_at
        indexed_at = snapshot.indexed_at
        return {
            "id": snapshot.hh_vacancy_id,
            "hh_vacancy_id": snapshot.hh_vacancy_id,
            "title": snapshot.title,
            "primary_role": snapshot.primary_role,
            "grade": snapshot.grade,
            "city": snapshot.city,
            "city_tier": snapshot.city_tier,
            "country": snapshot.country,
            "region": snapshot.region,
            "city_normalized": snapshot.city_normalized,
            "geo_scope": snapshot.geo_scope,
            "salary_from": snapshot.salary_from,
            "salary_to": snapshot.salary_to,
            "skills": snapshot.skills,
            "description_snippet": snapshot.description_snippet,
            "url": snapshot.url,
            "hh_url": snapshot.hh_url or snapshot.url,
            "published_at": _datetime_to_iso(published_at),
            "indexed_at": _datetime_to_iso(indexed_at),
            "dataset_run_id": snapshot.dataset_run_id,
        }


def _is_index_not_found(exc: Exception) -> bool:
    text = str(exc).lower()
    return "index_not_found" in text or "index `vacancies` not found" in text or "index not found" in text


def _search_result_total(result: Any) -> int:
    if isinstance(result, dict):
        for key in ("estimatedTotalHits", "totalHits", "estimated_total_hits", "total_hits"):
            value = result.get(key)
            if value is not None:
                return int(value)
        hits = result.get("hits")
        return len(hits) if isinstance(hits, list) else 0

    for attr in ("estimated_total_hits", "estimatedTotalHits", "total_hits", "totalHits"):
        value = getattr(result, attr, None)
        if value is not None:
            return int(value)
    hits = getattr(result, "hits", None)
    return len(hits) if isinstance(hits, list) else 0


def _datetime_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
