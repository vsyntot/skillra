"""Admin endpoints: reload-data, index-meilisearch, notify-data-updated.

Sprint-009 TASK-01: Added index-meilisearch endpoint and background vacancy indexer.
Sprint-009 TASK-07: Added notify-data-updated endpoint.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from skillra_api.config import Settings
from skillra_api.datastore import DataStore, DataStoreLoadPaths
from skillra_api.db.models import ActiveDataset, DataRun, IndexerRun
from skillra_api.deps import get_datastore_dependency, get_redis_dependency, get_settings_dependency
from skillra_api.deps.auth import require_admin_token, require_service_token
from skillra_api.metrics import (
    DATASTORE_RELOAD_FAILURES_TOTAL,
    DATASTORE_RELOAD_LAST_FAILURE_TIMESTAMP_SECONDS,
    DATASTORE_RELOAD_LAST_SUCCESS_TIMESTAMP_SECONDS,
    DATASTORE_RELOAD_REDIS_PUBLISH_FAILURES_TOTAL,
    DATASTORE_RELOADS_TOTAL,
    VACANCY_INDEXER_FAILURES_TOTAL,
    VACANCY_INDEXER_LAST_FAILURE_TIMESTAMP_SECONDS,
    VACANCY_INDEXER_LAST_INDEXED_TOTAL,
    VACANCY_INDEXER_LAST_SUCCESS_TIMESTAMP_SECONDS,
)
from skillra_api.schemas import (
    ActiveDatasetOut,
    ActiveDatasetStatusOut,
    DataRunOut,
    DataRunStateUpdateIn,
    DataRunStatusOut,
    IndexerStatusOut,
)
from skillra_api.services.data_runs import (
    DataRunStateError,
    activate_data_run,
    active_dataset_run,
    latest_data_run,
    list_data_runs,
    upsert_data_run_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_service_token), Depends(require_admin_token)],
)


@dataclass(frozen=True)
class ActiveReloadPlan:
    """Verified active dataset paths for one reload-data call."""

    run_id: str
    paths: DataStoreLoadPaths
    verified_artifacts: list[str]


class ActiveDatasetArtifactError(RuntimeError):
    """Raised when the active Dataset Registry pointer cannot be served safely."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _run_to_status(
    run: IndexerRun,
    *,
    served_dataset_run_id: str | None = None,
    active_dataset_run_id: str | None = None,
) -> IndexerStatusOut:
    return IndexerStatusOut(
        status=run.status,
        source=run.source,
        dataset_run_id=run.dataset_run_id or _dataset_run_id_from_indexer_source(run.source),
        served_dataset_run_id=served_dataset_run_id,
        active_dataset_run_id=active_dataset_run_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        inserted=run.inserted,
        indexed=run.indexed,
        error_msg=run.error_msg,
    )


def _data_run_to_out(run: DataRun) -> DataRunOut:
    return DataRunOut(
        run_id=run.run_id,
        state=run.state,
        source=run.source,
        started_at=run.started_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
        raw_rows=run.raw_rows,
        processed_rows=run.processed_rows,
        error_msg=run.error_msg,
        dataset_meta_path=run.dataset_meta_path,
        manifest_uri=run.manifest_uri,
        quality_report_uri=run.quality_report_uri,
        artifact_uris=run.artifact_uris,
        raw_quality_report=run.raw_quality_report,
        processed_quality_report=run.processed_quality_report,
        product_eligibility=run.product_eligibility,
        source_capability_ref=run.source_capability_ref,
    )


def _active_dataset_to_out(active: ActiveDataset, run: DataRun | None) -> ActiveDatasetOut:
    return ActiveDatasetOut(
        run_id=active.run_id,
        activated_at=active.activated_at,
        source=active.source,
        dataset_meta_path=active.dataset_meta_path,
        manifest_uri=active.manifest_uri,
        quality_report_uri=active.quality_report_uri,
        raw_rows=active.raw_rows,
        processed_rows=active.processed_rows,
        run=_data_run_to_out(run) if run is not None else None,
    )


def _model_json(model: Any) -> Any:
    """Serialize Pydantic v2 models without FastAPI's v1 compatibility checks."""

    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, list):
        return [_model_json(item) for item in model]
    return model


async def _create_indexer_run(
    session_maker: async_sessionmaker[AsyncSession],
    source: str,
    *,
    dataset_run_id: str | None = None,
) -> int:
    async with session_maker() as session:
        run = IndexerRun(
            started_at=_now_utc(),
            status="running",
            source=source,
            dataset_run_id=dataset_run_id,
            inserted=0,
            indexed=0,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


def _set_indexer_success(*args: Any) -> Any:
    """Update indexer success metrics, or return DB persistence coroutine.

    The two-argument form is kept for older metrics tests that exercised the
    former in-memory status helper directly.
    """

    if len(args) == 2:
        result, _source = args
        now = _now_utc()
        indexed = int(result.get("indexed", 0))
        VACANCY_INDEXER_LAST_SUCCESS_TIMESTAMP_SECONDS.set(now.timestamp())
        VACANCY_INDEXER_LAST_INDEXED_TOTAL.set(indexed)
        return None
    if len(args) == 3:
        session_maker, run_id, result = args
        return _set_indexer_success_db(session_maker, run_id, result)
    msg = "_set_indexer_success expects (result, source) or (session_maker, run_id, result)"
    raise TypeError(msg)


async def _set_indexer_success_db(
    session_maker: async_sessionmaker[AsyncSession], run_id: int, result: dict[str, Any]
) -> None:
    now = _now_utc()
    indexed = int(result.get("indexed", 0))
    async with session_maker() as session:
        run = await session.get(IndexerRun, run_id)
        if run is not None:
            run.status = "success"
            run.finished_at = now
            run.inserted = int(result.get("inserted", 0))
            run.indexed = indexed
            run.error_msg = None
            await session.commit()
    VACANCY_INDEXER_LAST_SUCCESS_TIMESTAMP_SECONDS.set(now.timestamp())
    VACANCY_INDEXER_LAST_INDEXED_TOTAL.set(indexed)


def _set_indexer_failure(*args: Any) -> Any:
    """Update indexer failure metrics, or return DB persistence coroutine."""

    if len(args) == 2:
        exc, _source = args
        now = _now_utc()
        VACANCY_INDEXER_LAST_FAILURE_TIMESTAMP_SECONDS.set(now.timestamp())
        VACANCY_INDEXER_FAILURES_TOTAL.inc()
        logger.debug("indexer failure recorded: %s", exc)
        return None
    if len(args) == 3:
        session_maker, run_id, exc = args
        return _set_indexer_failure_db(session_maker, run_id, exc)
    msg = "_set_indexer_failure expects (exc, source) or (session_maker, run_id, exc)"
    raise TypeError(msg)


async def _set_indexer_failure_db(
    session_maker: async_sessionmaker[AsyncSession], run_id: int, exc: BaseException
) -> None:
    now = _now_utc()
    async with session_maker() as session:
        run = await session.get(IndexerRun, run_id)
        if run is not None:
            run.status = "failed"
            run.finished_at = now
            run.error_msg = str(exc)
            await session.commit()
    VACANCY_INDEXER_LAST_FAILURE_TIMESTAMP_SECONDS.set(now.timestamp())
    VACANCY_INDEXER_FAILURES_TOTAL.inc()


async def _get_indexer_status(
    session_maker: async_sessionmaker[AsyncSession] | None,
    *,
    served_dataset_run_id: str | None = None,
) -> IndexerStatusOut:
    if session_maker is None:
        return IndexerStatusOut(status="idle", served_dataset_run_id=served_dataset_run_id)
    async with session_maker() as session:
        run = await session.scalar(select(IndexerRun).order_by(IndexerRun.started_at.desc(), IndexerRun.id.desc()))
    active, _active_run = await active_dataset_run(session_maker)
    active_dataset_run_id = active.run_id if active is not None else None
    return (
        _run_to_status(
            run,
            served_dataset_run_id=served_dataset_run_id,
            active_dataset_run_id=active_dataset_run_id,
        )
        if run is not None
        else IndexerStatusOut(
            status="idle",
            served_dataset_run_id=served_dataset_run_id,
            active_dataset_run_id=active_dataset_run_id,
        )
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


def _path_from_meta(meta: dict[str, Any], key: str, fallback: Path) -> str:
    raw = meta.get(key)
    return str(raw) if raw else str(fallback)


def _snapshot_history_path_from_meta(meta: dict[str, Any]) -> str:
    raw = meta.get("market_snapshot_path")
    if raw:
        path = Path(str(raw))
        return str(path.parent if path.suffix else path)
    return str(Path("data") / "processed" / "market_snapshots")


def _resolve_local_path(path_str: str) -> Path:
    return Path(path_str).expanduser()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_sha_map(run: DataRun) -> dict[str, str]:
    artifact_uris = run.artifact_uris if isinstance(run.artifact_uris, dict) else {}
    artifacts = artifact_uris.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    result: dict[str, str] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        sha = artifact.get("sha256")
        path = artifact.get("path")
        lake_key = artifact.get("lake_key")
        if not sha:
            continue
        for key in (path, lake_key):
            if key:
                result[str(key)] = str(sha)
        if path:
            result[Path(str(path)).name] = str(sha)
        if lake_key:
            result[Path(str(lake_key)).name] = str(sha)
    return result


def _expected_sha_for(path: Path, sha_by_key: dict[str, str]) -> str | None:
    candidates = [str(path), path.as_posix(), path.name]
    try:
        candidates.append(str(path.resolve()))
    except OSError:
        pass
    for candidate in candidates:
        if candidate in sha_by_key:
            return sha_by_key[candidate]
    return None


def _verify_artifact(path_str: str, *, label: str, sha_by_key: dict[str, str]) -> str:
    path = _resolve_local_path(path_str)
    if not path.exists():
        raise ActiveDatasetArtifactError(f"{label} artifact not found: {path}")
    expected_sha = _expected_sha_for(path, sha_by_key)
    if not expected_sha:
        raise ActiveDatasetArtifactError(f"{label} artifact checksum is missing from Dataset Registry: {path}")
    actual_sha = _sha256(path)
    if actual_sha != expected_sha:
        raise ActiveDatasetArtifactError(f"{label} artifact checksum mismatch: {path}")
    return label


async def _active_reload_plan(
    session_maker: async_sessionmaker[AsyncSession] | None,
) -> ActiveReloadPlan | None:
    if session_maker is None or not callable(session_maker):
        return None
    active, run = await active_dataset_run(session_maker)
    if active is None:
        return None
    if run is None:
        raise ActiveDatasetArtifactError(f"Active dataset run {active.run_id!r} is missing from data_runs.")
    if run.state != "published":
        raise ActiveDatasetArtifactError(f"Active dataset run {run.run_id!r} is {run.state!r}, not published.")
    if not active.dataset_meta_path:
        raise ActiveDatasetArtifactError(f"Active dataset run {run.run_id!r} has no dataset_meta_path.")

    dataset_meta_path = _resolve_local_path(active.dataset_meta_path)
    if not dataset_meta_path.exists():
        raise ActiveDatasetArtifactError(f"Active dataset metadata not found: {dataset_meta_path}")
    try:
        dataset_meta = json.loads(dataset_meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ActiveDatasetArtifactError(f"Active dataset metadata is unreadable: {dataset_meta_path}") from exc
    if not isinstance(dataset_meta, dict):
        raise ActiveDatasetArtifactError("Active dataset metadata must be a JSON object.")
    meta_run_id = dataset_meta.get("run_id")
    if str(meta_run_id or "") != run.run_id:
        raise ActiveDatasetArtifactError(
            f"Active dataset meta run_id {meta_run_id!r} != registry run_id {run.run_id!r}."
        )

    run_dir = dataset_meta_path.parent
    paths = DataStoreLoadPaths(
        features_path=_path_from_meta(dataset_meta, "features_path", run_dir / "hh_features.parquet"),
        market_view_path=_path_from_meta(dataset_meta, "market_view_path", run_dir / "market_view.parquet"),
        dataset_meta_path=str(dataset_meta_path),
        market_snapshots_path=_snapshot_history_path_from_meta(dataset_meta),
    )
    sha_by_key = _artifact_sha_map(run)
    verified = [
        _verify_artifact(paths.dataset_meta_path, label="dataset_meta", sha_by_key=sha_by_key),
        _verify_artifact(paths.features_path, label="features", sha_by_key=sha_by_key),
        _verify_artifact(paths.market_view_path, label="market_view", sha_by_key=sha_by_key),
    ]
    return ActiveReloadPlan(run_id=run.run_id, paths=paths, verified_artifacts=verified)


def _set_datastore_reload_success() -> None:
    now = _now_utc()
    DATASTORE_RELOADS_TOTAL.labels(status="success").inc()
    DATASTORE_RELOAD_LAST_SUCCESS_TIMESTAMP_SECONDS.set(now.timestamp())


def _set_datastore_reload_failure(stage: str, exc: BaseException) -> None:
    now = _now_utc()
    bounded_stage = stage if stage in {"datastore", "indexer", "unknown"} else "unknown"
    DATASTORE_RELOADS_TOTAL.labels(status="failed").inc()
    DATASTORE_RELOAD_FAILURES_TOTAL.labels(stage=bounded_stage).inc()
    DATASTORE_RELOAD_LAST_FAILURE_TIMESTAMP_SECONDS.set(now.timestamp())
    logger.debug("datastore reload failure recorded at stage=%s: %s", bounded_stage, exc)


async def _delete_meta_cache(redis: Any | None) -> None:
    if redis is None:
        return
    try:
        keys = [key async for key in redis.scan_iter(match="meta:*")]
        if keys:
            await redis.delete(*keys)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to delete Redis meta cache", exc_info=True)


async def _upsert_market_snapshots(session_maker: async_sessionmaker[AsyncSession], datastore: DataStore) -> int:
    from skillra_api.services.snapshot_service import upsert_snapshots

    snapshots_df = datastore.get_snapshot_history_df()
    if snapshots_df.empty:
        return 0
    async with session_maker() as session:
        return await upsert_snapshots(session, snapshots_df)


async def _bg_index_vacancies(
    session_maker: async_sessionmaker[AsyncSession],
    datastore: DataStore,
    settings: Settings,
) -> None:
    """Background task: sync vacancy_snapshots from parquet and re-index MeiliSearch."""
    try:
        await _run_vacancy_indexer(session_maker, datastore, settings, source="background")
    except Exception:  # noqa: BLE001
        logger.exception("bg-vacancy-indexer: failed")


async def _run_vacancy_indexer(
    session_maker: async_sessionmaker[AsyncSession],
    datastore: DataStore,
    settings: Settings,
    *,
    source: str,
) -> dict[str, Any]:
    """Sync vacancy snapshots and search index, surfacing failures to callers."""

    from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots_incremental

    dataset_run_id = _dataset_run_id(datastore)
    run_id = await _create_indexer_run(session_maker, source, dataset_run_id=dataset_run_id)
    try:
        features_df = datastore.get_features_df()
        async with session_maker() as session:
            result = await sync_vacancy_snapshots_incremental(
                session,
                features_df,
                settings,
                dataset_run_id=dataset_run_id,
            )
    except Exception as exc:
        await _set_indexer_failure(session_maker, run_id, exc)
        raise

    await _set_indexer_success(session_maker, run_id, result)
    logger.info(
        "vacancy-indexer: completed",
        extra={"source": source, "inserted": result.get("inserted"), "indexed": result.get("indexed")},
    )
    return {"run_id": run_id, "dataset_run_id": dataset_run_id, "status": "success", **result}


@router.post("/reload-data", response_class=JSONResponse)
async def reload_data(
    request: Request,
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> JSONResponse:
    """Reload parquet datasets with admin token protection.

    Sprint-009 TASK-01: After reload, starts background task to re-index vacancies.
    """
    previous_state = datastore.snapshot_state()
    previous_dataset_run_id = _dataset_run_id(datastore)
    session_maker = getattr(request.app.state, "session_maker", None)
    try:
        active_plan = await _active_reload_plan(session_maker)
    except ActiveDatasetArtifactError as exc:
        _set_datastore_reload_failure("datastore", exc)
        logger.exception("reload-data: active dataset artifact validation failed")
        datastore.restore_state(previous_state)
        return JSONResponse(
            status_code=500,
            content={
                "status": "reload_failed",
                "error": "active_dataset_artifact_invalid",
                "detail": str(exc),
                "dataset_run_id": None,
                "served_dataset_run_id": previous_dataset_run_id,
                "datastore": datastore.status(),
                "market_snapshots_upserted": 0,
            },
        )
    try:
        if active_plan is None:
            await datastore.areload()
        else:
            await datastore.areload_from_paths(active_plan.paths)
        dataset_run_id = _dataset_run_id(datastore)
        if active_plan is not None and dataset_run_id != active_plan.run_id:
            raise ActiveDatasetArtifactError(
                f"Loaded dataset run {dataset_run_id!r} does not match active run {active_plan.run_id!r}."
            )
        if not getattr(datastore, "is_ready", True):
            raise ActiveDatasetArtifactError("DataStore is not ready after active dataset reload.")
    except Exception as exc:  # noqa: BLE001
        _set_datastore_reload_failure("datastore", exc)
        logger.exception("reload-data: datastore reload failed")
        datastore.restore_state(previous_state)
        return JSONResponse(
            status_code=500,
            content={
                "status": "reload_failed",
                "error": "datastore_reload_failed",
                "detail": str(exc),
                "dataset_run_id": None,
                "served_dataset_run_id": previous_dataset_run_id,
                "datastore": datastore.status(),
                "market_snapshots_upserted": 0,
            },
        )
    dataset_run_id = _dataset_run_id(datastore)

    indexer_result: dict[str, Any] | None = None
    if session_maker is not None:
        try:
            indexer_result = await _run_vacancy_indexer(session_maker, datastore, settings, source="reload")
            snapshots_upserted = await _upsert_market_snapshots(session_maker, datastore)
        except Exception as exc:  # noqa: BLE001
            _set_datastore_reload_failure("indexer", exc)
            logger.exception("reload-data: vacancy indexer failed")
            datastore.restore_state(previous_state)
            return JSONResponse(
                status_code=500,
                content={
                    "status": "reload_failed",
                    "error": "vacancy_indexer_failed",
                    "detail": str(exc),
                    "dataset_run_id": dataset_run_id,
                    "served_dataset_run_id": previous_dataset_run_id,
                    "datastore": datastore.status(),
                    "market_snapshots_upserted": 0,
                },
            )
    else:
        snapshots_upserted = 0

    await _delete_meta_cache(redis)
    if redis is not None:
        try:
            await redis.publish(
                "datastore_reload",
                json.dumps({"timestamp": _now_utc().isoformat(), "dataset_run_id": dataset_run_id}),
            )
        except Exception:  # noqa: BLE001
            DATASTORE_RELOAD_REDIS_PUBLISH_FAILURES_TOTAL.inc()
            logger.warning("Failed to publish datastore_reload event", exc_info=True)

    _set_datastore_reload_success()
    return JSONResponse(
        content={
            "status": "reloaded",
            "dataset_run_id": dataset_run_id,
            "active_dataset_run_id": active_plan.run_id if active_plan is not None else None,
            "verified_artifacts": active_plan.verified_artifacts if active_plan is not None else [],
            "datastore": datastore.status(),
            "market_snapshots_upserted": snapshots_upserted,
            "indexer": indexer_result,
        }
    )


@router.post("/index-meilisearch", response_class=JSONResponse)
async def index_meilisearch(
    request: Request,
    force: bool = Query(False, description="Force full refresh instead of incremental sync"),
    datastore: DataStore = Depends(get_datastore_dependency),
    settings: Settings = Depends(get_settings_dependency),
) -> JSONResponse:
    """Sync vacancy_snapshots from parquet and re-index MeiliSearch.

    Full-refresh strategy: truncates vacancy_snapshots table, re-imports from
    hh_features.parquet, then pushes all documents to MeiliSearch.
    Sprint-009 TASK-01.
    """
    from skillra_api.services.vacancy_indexer import sync_vacancy_snapshots_incremental

    if not datastore.is_ready:
        return JSONResponse(status_code=503, content={"error": "DataStore not ready"})

    try:
        features_df = datastore.get_features_df()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"error": f"DataStore error: {exc}"})

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return JSONResponse(status_code=503, content={"error": "Database not configured"})

    dataset_run_id = _dataset_run_id(datastore)
    run_id = await _create_indexer_run(session_maker, "manual", dataset_run_id=dataset_run_id)
    try:
        async with session_maker() as db_session:
            result = await sync_vacancy_snapshots_incremental(
                db_session,
                features_df,
                settings,
                force_full=force,
                dataset_run_id=dataset_run_id,
            )
    except Exception as exc:  # noqa: BLE001
        await _set_indexer_failure(session_maker, run_id, exc)
        logger.exception("index-meilisearch failed")
        return JSONResponse(status_code=500, content={"error": str(exc)})

    await _set_indexer_success(session_maker, run_id, result)
    return JSONResponse(content={"status": "ok", "dataset_run_id": dataset_run_id, **result})


@router.get("/indexer-status", response_model=IndexerStatusOut, response_class=JSONResponse)
async def indexer_status(
    request: Request,
    datastore: DataStore = Depends(get_datastore_dependency),
) -> JSONResponse:
    """Return the last known vacancy indexer state."""

    status = await _get_indexer_status(
        getattr(request.app.state, "session_maker", None),
        served_dataset_run_id=_dataset_run_id(datastore),
    )
    return JSONResponse(content=_model_json(status))


@router.post("/data-runs/{run_id}/state", response_model=DataRunOut, response_class=JSONResponse)
async def update_data_run_state(
    run_id: str,
    payload: DataRunStateUpdateIn,
    request: Request,
) -> JSONResponse:
    """Create or update an end-to-end data pipeline run state."""

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return JSONResponse(status_code=503, content={"error": "Database not configured"})

    try:
        run = await upsert_data_run_state(
            session_maker,
            run_id=run_id,
            state=payload.state,
            source=payload.source,
            raw_rows=payload.raw_rows,
            processed_rows=payload.processed_rows,
            error_msg=payload.error_msg,
            dataset_meta_path=payload.dataset_meta_path,
            manifest_uri=payload.manifest_uri,
            quality_report_uri=payload.quality_report_uri,
            artifact_uris=payload.artifact_uris,
            raw_quality_report=payload.raw_quality_report,
            processed_quality_report=payload.processed_quality_report,
            product_eligibility=payload.product_eligibility,
            source_capability_ref=payload.source_capability_ref,
        )
    except DataRunStateError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    return JSONResponse(content=_model_json(_data_run_to_out(run)))


@router.post("/data-runs/{run_id}/activate", response_model=ActiveDatasetStatusOut, response_class=JSONResponse)
async def activate_data_run_pointer(run_id: str, request: Request) -> JSONResponse:
    """Activate a previously published data run without mutating artifacts."""

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return JSONResponse(status_code=503, content={"error": "Database not configured"})

    try:
        active, run = await activate_data_run(session_maker, run_id=run_id)
    except DataRunStateError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    return JSONResponse(
        content=_model_json(ActiveDatasetStatusOut(state=run.state, active=_active_dataset_to_out(active, run)))
    )


@router.get("/data-runs/latest", response_model=DataRunStatusOut, response_class=JSONResponse)
async def data_run_latest(request: Request) -> JSONResponse:
    """Return the latest known end-to-end data pipeline run state."""

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return JSONResponse(content=_model_json(DataRunStatusOut(state="not_configured", latest=None)))

    run = await latest_data_run(session_maker)
    if run is None:
        return JSONResponse(content=_model_json(DataRunStatusOut(state="idle", latest=None)))
    return JSONResponse(content=_model_json(DataRunStatusOut(state=run.state, latest=_data_run_to_out(run))))


@router.get("/data-runs/active", response_model=ActiveDatasetStatusOut, response_class=JSONResponse)
async def data_run_active(request: Request) -> JSONResponse:
    """Return the active published dataset pointer."""

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return JSONResponse(content=_model_json(ActiveDatasetStatusOut(state="not_configured", active=None)))

    active, run = await active_dataset_run(session_maker)
    if active is None:
        return JSONResponse(content=_model_json(ActiveDatasetStatusOut(state="idle", active=None)))
    state = run.state if run is not None else "missing_run"
    return JSONResponse(
        content=_model_json(ActiveDatasetStatusOut(state=state, active=_active_dataset_to_out(active, run)))
    )


@router.get("/data-runs", response_model=list[DataRunOut], response_class=JSONResponse)
async def data_run_history(request: Request, limit: int = Query(20, ge=1, le=100)) -> JSONResponse:
    """Return recent end-to-end data pipeline run states."""

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        return JSONResponse(status_code=503, content={"error": "Database not configured"})

    runs = await list_data_runs(session_maker, limit=limit)
    return JSONResponse(content=_model_json([_data_run_to_out(run) for run in runs]))


@router.post("/notify-data-updated", response_class=JSONResponse)
async def notify_data_updated(
    request: Request,
) -> JSONResponse:
    """Trigger market-data-updated notification via Redis pub/sub.

    Called by data-scheduler after successful reload.
    Sprint-009 TASK-07.
    """
    redis = getattr(request.app.state, "redis", None)
    if redis:
        try:
            await redis.publish("market_updated", "1")
            return JSONResponse(content={"status": "published"})
        except Exception as exc:  # noqa: BLE001
            logger.exception("notify-data-updated: publish failed")
            return JSONResponse(status_code=500, content={"error": str(exc)})
    return JSONResponse(status_code=503, content={"status": "redis_unavailable"})
