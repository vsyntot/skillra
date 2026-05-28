from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from skillra_api.config import Settings
from skillra_api.constants import API_VERSION
from skillra_api.datastore import DataStore
from skillra_api.db.models import IndexerRun
from skillra_api.deps import get_datastore_dependency, get_redis_dependency, get_settings_dependency
from skillra_api.deps.auth import require_service_token
from skillra_api.services.data_runs import active_dataset_run, latest_data_run

router = APIRouter()


def _health_payload(settings: Settings) -> dict[str, Any]:
    return {
        "status": "ok",
        "message": "Skillra API is running.",
        "version": API_VERSION,
        "runtime_env": settings.runtime_env,
        "public_base_url": settings.public_base_url,
    }


@router.get("/health", response_class=JSONResponse, tags=["health"])
async def service_healthcheck(settings: Settings = Depends(get_settings_dependency)) -> dict[str, Any]:
    """Return a minimal health payload for the scaffolded API."""

    return _health_payload(settings)


@router.get("/", response_class=JSONResponse, tags=["health"])
async def root(settings: Settings = Depends(get_settings_dependency)) -> dict[str, Any]:
    """Return a small index payload for manual browser checks."""

    return {**_health_payload(settings), "docs": "/docs", "health": "/health"}


def _migration_status(request: Request) -> dict[str, Any]:
    raw_status = getattr(request.app.state, "migration_status", None)
    if not isinstance(raw_status, dict):
        return {"status": "not_configured", "current": None, "head": None}
    if not raw_status.get("status"):
        return {**raw_status, "status": "unknown"}
    return raw_status


@router.get("/v1/auth/check", response_class=JSONResponse, tags=["auth"])
async def auth_check(_: None = Depends(require_service_token)) -> dict[str, str]:
    """Validate the service token used by browser clients."""

    return {"status": "ok"}


@router.get("/v1/health", response_class=JSONResponse, tags=["health"])
async def data_healthcheck(
    request: Request,
    settings: Settings = Depends(get_settings_dependency),
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> Any:
    """Return dependency health without failing on partial outages."""

    return await _dependency_health_payload(request, settings, datastore, redis)


@router.get("/v1/ready", response_class=JSONResponse, tags=["health"])
async def readiness_check(
    request: Request,
    settings: Settings = Depends(get_settings_dependency),
    datastore: DataStore = Depends(get_datastore_dependency),
    redis: Any | None = Depends(get_redis_dependency),
) -> JSONResponse:
    """Return strict readiness for routing and deploy smoke checks."""

    payload = await _dependency_health_payload(request, settings, datastore, redis)
    status_code = 200 if payload.get("status") == "ok" else 503
    return JSONResponse(status_code=status_code, content=payload)


async def _dependency_health_payload(
    request: Request,
    settings: Settings,
    datastore: DataStore,
    redis: Any | None,
) -> dict[str, Any]:
    """Build the shared dependency health payload used by health and readiness."""

    database_status = "not_configured"
    session_maker = getattr(request.app.state, "session_maker", None)
    datastore_state = datastore.status()
    datastore_status = "ok" if datastore.is_ready else "error"
    redis_status = await _redis_status(redis)
    meili_status = await _current_meilisearch_status(request, settings)
    migration_status = _migration_status(request)
    data_run_status = await _data_run_status(session_maker)
    dataset_run_id = _dataset_run_id(datastore)
    data_consistency = _data_consistency_status(dataset_run_id, data_run_status)
    search_publish = await _search_publish_status(session_maker, dataset_run_id)
    data_consistency_check = data_consistency
    if data_consistency == "unknown" and datastore.is_ready and session_maker is not None:
        data_consistency_check = "degraded"
    search_publish_check = search_publish["status"]
    if search_publish_check == "unknown" and datastore.is_ready and session_maker is not None:
        search_publish_check = "degraded"

    payload: dict[str, Any] = {
        **_health_payload(settings),
        "database": database_status,
        "redis": redis_status,
        "meilisearch": meili_status,
        "migrations": migration_status,
        "data_run": data_run_status,
        "search_publish": search_publish,
        "dataset_run_id": dataset_run_id,
        "data_consistency": data_consistency,
        "datastore": datastore_state,
        "datastore_status": datastore_status,
    }
    if session_maker is not None:
        payload["database"] = await _database_status(session_maker)
    elif not datastore.is_ready:
        payload["database"] = "not_configured"

    checks = [
        payload["database"],
        payload["redis"],
        payload["meilisearch"],
        payload["datastore_status"],
        migration_status["status"],
        data_consistency_check,
        search_publish_check,
        "error"
        if data_run_status.get("state") == "error"
        else "degraded"
        if data_run_status.get("state") == "failed"
        else "ok",
    ]
    if "error" in checks:
        payload["status"] = "degraded"
    elif "degraded" in checks:
        payload["status"] = "degraded"
    return payload


def _dataset_run_id(datastore: DataStore) -> str | None:
    meta = datastore.get_dataset_meta() or {}
    run_id = meta.get("run_id")
    return str(run_id) if run_id else None


def _data_consistency_status(dataset_run_id: str | None, data_run_status: dict[str, Any]) -> str:
    active = data_run_status.get("active")
    if dataset_run_id and isinstance(active, dict):
        active_run_id = active.get("run_id")
        active_state = active.get("state")
        if active_run_id == dataset_run_id and active_state == "published":
            return "ok"
        if active_run_id and active_run_id != dataset_run_id:
            return "degraded"
        if active_run_id and active_state != "published":
            return "degraded"

    latest = data_run_status.get("latest")
    if not dataset_run_id or not isinstance(latest, dict):
        return "unknown"
    latest_run_id = latest.get("run_id")
    state = data_run_status.get("state")
    if state == "published" and latest_run_id == dataset_run_id:
        return "ok"
    if latest_run_id and latest_run_id != dataset_run_id:
        return "degraded"
    return "unknown"


async def _database_status(session_maker: Any | None) -> str:
    if session_maker is None:
        return "not_configured"
    try:
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001
        return "error"


async def _data_run_status(session_maker: Any | None) -> dict[str, Any]:
    if session_maker is None:
        return {"state": "not_configured", "latest": None, "active": None}
    try:
        run = await latest_data_run(session_maker)
        active, active_run = await active_dataset_run(session_maker)
    except Exception as exc:  # noqa: BLE001
        return {"state": "error", "latest": None, "active": None, "error": str(exc)}
    if run is None:
        return {"state": "idle", "latest": None, "active": None}
    active_payload = None
    if active is not None:
        active_payload = {
            "run_id": active.run_id,
            "state": active_run.state if active_run is not None else "missing_run",
            "activated_at": active.activated_at.isoformat(),
            "source": active.source,
            "dataset_meta_path": active.dataset_meta_path,
            "manifest_uri": active.manifest_uri,
            "quality_report_uri": active.quality_report_uri,
        }
    return {
        "state": run.state,
        "latest": {
            "run_id": run.run_id,
            "started_at": run.started_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "source": run.source,
        },
        "active": active_payload,
    }


async def _search_publish_status(session_maker: Any | None, dataset_run_id: str | None) -> dict[str, Any]:
    if session_maker is None:
        return {"status": "not_configured", "dataset_run_id": None, "indexed": 0}
    previous_success = None
    try:
        async with session_maker() as session:
            run = await session.scalar(select(IndexerRun).order_by(IndexerRun.started_at.desc(), IndexerRun.id.desc()))
            if dataset_run_id and run is not None and run.status == "running":
                previous_success = await session.scalar(
                    select(IndexerRun)
                    .where(IndexerRun.dataset_run_id == dataset_run_id, IndexerRun.status == "success")
                    .order_by(IndexerRun.started_at.desc(), IndexerRun.id.desc())
                )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "dataset_run_id": None, "indexed": 0, "error": str(exc)}
    if run is None:
        return {"status": "unknown", "dataset_run_id": None, "indexed": 0}

    run_dataset_id = run.dataset_run_id
    if run.status == "running" and previous_success is not None:
        return {
            "status": "ok",
            "dataset_run_id": previous_success.dataset_run_id,
            "source": previous_success.source,
            "indexed": previous_success.indexed,
            "finished_at": previous_success.finished_at.isoformat() if previous_success.finished_at else None,
            "error_msg": previous_success.error_msg,
            "in_progress": True,
            "latest_status": run.status,
            "latest_source": run.source,
            "latest_started_at": run.started_at.isoformat(),
        }
    if run.status == "success" and dataset_run_id and run_dataset_id == dataset_run_id:
        status = "ok"
    elif run.status == "failed":
        status = "degraded"
    elif dataset_run_id and run_dataset_id and run_dataset_id != dataset_run_id:
        status = "degraded"
    else:
        status = "unknown"

    return {
        "status": status,
        "dataset_run_id": run_dataset_id,
        "source": run.source,
        "indexed": run.indexed,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error_msg": run.error_msg,
    }


async def _redis_status(redis: Any | None) -> str:
    if redis is None:
        return "not_configured"
    try:
        await redis.ping()
        return "ok"
    except Exception:  # noqa: BLE001
        return "error"


async def _current_meilisearch_status(request: Request, settings: Settings) -> str:
    status = await _meilisearch_status(settings)
    request.app.state.meilisearch_status = status
    return status


async def _meilisearch_status(settings: Settings) -> str:
    if not settings.meilisearch_url:
        return "not_configured"
    try:
        from skillra_api.services.search import get_search_client

        client = await get_search_client(settings)
        if client is None:
            return "not_configured"
        await client.health()
        return "ok"
    except Exception:  # noqa: BLE001
        return "degraded"
