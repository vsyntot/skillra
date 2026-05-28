"""Persistence helpers for end-to-end data pipeline run state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from skillra_api.db.models import ActiveDataset, DataRun
from skillra_api.metrics import (
    DATA_RUN_LAST_FAILURE_TIMESTAMP_SECONDS,
    DATA_RUN_LAST_SUCCESS_TIMESTAMP_SECONDS,
    DATA_RUN_PROCESSED_ROWS,
    DATA_RUN_RAW_ROWS,
    DATA_RUN_STATE,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DATA_RUN_STATES = {
    "collecting",
    "raw_committed",
    "raw_validated",
    "processing",
    "processed_validated",
    "staged",
    "indexing",
    "published",
    "failed",
}
TERMINAL_DATA_RUN_STATES = {"published", "failed"}
DATA_RUN_STATE_ORDER = {
    "collecting": 10,
    "raw_committed": 20,
    "raw_validated": 30,
    "processing": 40,
    "processed_validated": 50,
    "staged": 60,
    "indexing": 70,
    "published": 80,
    "failed": 90,
}


class DataRunStateError(ValueError):
    """Raised when an invalid data run state transition request is received."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def validate_data_run_state(state: str) -> None:
    if state not in DATA_RUN_STATES:
        allowed = ", ".join(sorted(DATA_RUN_STATES))
        raise DataRunStateError(f"Invalid data run state {state!r}. Allowed states: {allowed}")


def validate_data_run_transition(current_state: str | None, next_state: str) -> None:
    """Reject state regressions while keeping first-write backfills compatible."""

    validate_data_run_state(next_state)
    if current_state is None:
        return
    if current_state == next_state:
        return
    if current_state in TERMINAL_DATA_RUN_STATES:
        raise DataRunStateError(f"Data run is terminal in state {current_state!r}; cannot move to {next_state!r}")
    if next_state != "failed" and DATA_RUN_STATE_ORDER[next_state] < DATA_RUN_STATE_ORDER[current_state]:
        raise DataRunStateError(f"Invalid data run transition {current_state!r} -> {next_state!r}")


def _record_data_run_metrics(run: DataRun) -> None:
    source = run.source or "unknown"
    for state in DATA_RUN_STATES:
        DATA_RUN_STATE.labels(state=state, source=source).set(1 if state == run.state else 0)

    if run.raw_rows is not None:
        DATA_RUN_RAW_ROWS.labels(source=source).set(run.raw_rows)
    if run.processed_rows is not None:
        DATA_RUN_PROCESSED_ROWS.labels(source=source).set(run.processed_rows)
    if run.finished_at is not None and run.state == "published":
        DATA_RUN_LAST_SUCCESS_TIMESTAMP_SECONDS.labels(source=source).set(run.finished_at.timestamp())
    if run.finished_at is not None and run.state == "failed":
        DATA_RUN_LAST_FAILURE_TIMESTAMP_SECONDS.labels(source=source).set(run.finished_at.timestamp())


def _apply_optional_registry_fields(
    run: DataRun,
    *,
    dataset_meta_path: str | None,
    manifest_uri: str | None,
    quality_report_uri: str | None,
    artifact_uris: dict[str, Any] | None,
    raw_quality_report: dict[str, Any] | None,
    processed_quality_report: dict[str, Any] | None,
    product_eligibility: dict[str, Any] | None,
    source_capability_ref: dict[str, Any] | None,
) -> None:
    if dataset_meta_path is not None:
        run.dataset_meta_path = dataset_meta_path
    if manifest_uri is not None:
        run.manifest_uri = manifest_uri
    if quality_report_uri is not None:
        run.quality_report_uri = quality_report_uri
    if artifact_uris is not None:
        run.artifact_uris = artifact_uris
    if raw_quality_report is not None:
        run.raw_quality_report = raw_quality_report
    if processed_quality_report is not None:
        run.processed_quality_report = processed_quality_report
    if product_eligibility is not None:
        run.product_eligibility = product_eligibility
    if source_capability_ref is not None:
        run.source_capability_ref = source_capability_ref


async def _set_active_dataset(session: AsyncSession, run: DataRun, *, activated_at: datetime) -> ActiveDataset:
    active = await session.get(ActiveDataset, 1)
    if active is None:
        active = ActiveDataset(id=1, run_id=run.run_id, activated_at=activated_at)
        session.add(active)
    active.run_id = run.run_id
    active.activated_at = activated_at
    active.source = run.source
    active.dataset_meta_path = run.dataset_meta_path
    active.manifest_uri = run.manifest_uri
    active.quality_report_uri = run.quality_report_uri
    active.raw_rows = run.raw_rows
    active.processed_rows = run.processed_rows
    return active


async def upsert_data_run_state(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
    state: str,
    source: str | None = None,
    raw_rows: int | None = None,
    processed_rows: int | None = None,
    error_msg: str | None = None,
    dataset_meta_path: str | None = None,
    manifest_uri: str | None = None,
    quality_report_uri: str | None = None,
    artifact_uris: dict[str, Any] | None = None,
    raw_quality_report: dict[str, Any] | None = None,
    processed_quality_report: dict[str, Any] | None = None,
    product_eligibility: dict[str, Any] | None = None,
    source_capability_ref: dict[str, Any] | None = None,
) -> DataRun:
    """Create or update a data run state row."""

    validate_data_run_state(state)
    current_time = now_utc()
    async with session_maker() as session:
        run = await session.scalar(select(DataRun).where(DataRun.run_id == run_id))
        if run is None:
            run = DataRun(
                run_id=run_id,
                state=state,
                source=source,
                started_at=current_time,
                updated_at=current_time,
            )
            session.add(run)
        else:
            validate_data_run_transition(run.state, state)
            run.state = state
            run.updated_at = current_time
            if source is not None:
                run.source = source

        if raw_rows is not None:
            run.raw_rows = raw_rows
        if processed_rows is not None:
            run.processed_rows = processed_rows
        if error_msg is not None:
            run.error_msg = error_msg
        elif state != "failed":
            run.error_msg = None

        _apply_optional_registry_fields(
            run,
            dataset_meta_path=dataset_meta_path,
            manifest_uri=manifest_uri,
            quality_report_uri=quality_report_uri,
            artifact_uris=artifact_uris,
            raw_quality_report=raw_quality_report,
            processed_quality_report=processed_quality_report,
            product_eligibility=product_eligibility,
            source_capability_ref=source_capability_ref,
        )
        run.finished_at = current_time if state in TERMINAL_DATA_RUN_STATES else None
        if state == "published":
            await _set_active_dataset(session, run, activated_at=current_time)

        await session.commit()
        await session.refresh(run)
        _record_data_run_metrics(run)
        return run


async def active_dataset_run(
    session_maker: async_sessionmaker[AsyncSession],
) -> tuple[ActiveDataset | None, DataRun | None]:
    async with session_maker() as session:
        active = await session.get(ActiveDataset, 1)
        if active is None:
            return None, None
        run = await session.scalar(select(DataRun).where(DataRun.run_id == active.run_id))
        return active, run


async def activate_data_run(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
) -> tuple[ActiveDataset, DataRun]:
    """Point the active dataset pointer at an already published data run."""

    async with session_maker() as session:
        run = await session.scalar(select(DataRun).where(DataRun.run_id == run_id))
        if run is None:
            raise DataRunStateError(f"Data run {run_id!r} does not exist.")
        if run.state != "published":
            raise DataRunStateError(f"Data run {run_id!r} is {run.state!r}; only published runs can be activated.")
        active = await _set_active_dataset(session, run, activated_at=now_utc())
        await session.commit()
        await session.refresh(active)
        await session.refresh(run)
        return active, run


async def latest_data_run(session_maker: async_sessionmaker[AsyncSession]) -> DataRun | None:
    async with session_maker() as session:
        return await session.scalar(select(DataRun).order_by(DataRun.started_at.desc(), DataRun.id.desc()))


async def list_data_runs(session_maker: async_sessionmaker[AsyncSession], *, limit: int = 20) -> Sequence[DataRun]:
    async with session_maker() as session:
        result = await session.scalars(
            select(DataRun).order_by(DataRun.started_at.desc(), DataRun.id.desc()).limit(limit)
        )
        return result.all()
