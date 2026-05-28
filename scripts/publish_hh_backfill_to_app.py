from __future__ import annotations

"""Publish completed HH backfill shards from MinIO into the application dataset.

The script is intentionally temporary and conservative:

* reads only ``backfills/<backfill_id>/date=YYYY-MM-DD/snapshot.csv`` objects
  for dates listed in backfill ``state.json.completed_dates``;
* ignores the currently collected partial day by default;
* materializes a deduplicated raw HH ``latest.csv`` under a separate local
  storage directory;
* runs the existing production data pipeline and optionally calls
  ``/v1/admin/reload-data``.

It does not stop or mutate the historical backfill job.
"""

import argparse
import asyncio
import csv
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.raw_hh_gate import validate_local_raw_hh  # noqa: E402
from skillra_pda.ingest.date_semantics import (  # noqa: E402
    build_cross_partition_duplicate_report,
    evaluate_csv_date_semantics,
)
from skillra_pda.ingest.hh_daily import (  # noqa: E402
    SCHEMA_VERSION,
    append_manifest_jsonl,
    build_manifest_payload,
    compute_delta,
    read_csv_columns,
    read_vacancy_ids,
    write_parquet_snapshot,
    write_state_json,
)
from skillra_pda.ingest.source_registry import validate_source_capability_ref  # noqa: E402
from skillra_pda.storage.s3_client import create_s3_client, download_bytes, get_file  # noqa: E402


DATE_FORMAT = "%Y-%m-%d"
DEFAULT_STORAGE_DIR = Path("data") / "raw" / "hh" / "backfill_publish"
DEFAULT_MIN_ROWS = 1
DATE_SEMANTICS_MAX_UNKNOWN_SHARE = 0.05
DATE_SEMANTICS_MAX_OUT_OF_WINDOW_SHARE = 0.0
ID_COLUMNS = ("vacancy_id", "hh_vacancy_id", "id")


@dataclass(frozen=True)
class PublishSelection:
    backfill_id: str
    bucket: str
    prefix: str
    completed_dates: list[str]
    selected_dates: list[str]
    current_date: str | None
    backfill_updated_at_utc: str | None
    quarantine: dict[str, Any] | None = None
    source_capability_ref: dict[str, Any] | None = None
    coverage_claim: str | None = None
    coverage_limitations: list[str] = field(default_factory=list)
    closed_archived_coverage: str | None = None


@dataclass(frozen=True)
class MaterializeResult:
    input_rows: int
    output_rows: int
    duplicate_rows: int
    skipped_missing_id: int
    per_date_rows: dict[str, int]
    snapshot_path: Path
    latest_path: Path
    parquet_snapshot_path: Path
    delta_path: Path
    state_path: Path
    duplicate_report_path: Path
    date_semantics: dict[str, Any]
    run_id: str
    selected_dates: list[str]


def resolve_dataset_semantic_type(selection: PublishSelection, date_semantics: dict[str, Any]) -> str:
    if selection.quarantine is not None:
        return "forensic_quarantined_snapshot"
    source_ref_failures = validate_source_capability_ref(
        selection.source_capability_ref,
        expected_use_case="historical_collection",
        require_supported=True,
    )
    coverage_claim = selection.coverage_claim
    if coverage_claim is None and isinstance(selection.source_capability_ref, dict):
        coverage_claim = selection.source_capability_ref.get("coverage_claim")
    if coverage_claim in {"", "unproven", "unproven_source_access"}:
        return "current_market_snapshot"
    if date_semantics.get("status") == "passed" and not source_ref_failures:
        return "historical_publication_facts"
    return "current_market_snapshot"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backfill-id",
        default=os.environ.get("SKILLRA_HH_BACKFILL_ID"),
        help="Backfill id under s3://<bucket>/backfills/. Defaults to SKILLRA_HH_BACKFILL_ID.",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("S3_BUCKET_RAW_HH"),
        help="Raw HH S3 bucket. Defaults to S3_BUCKET_RAW_HH.",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=DEFAULT_STORAGE_DIR,
        help=f"Local raw publish storage directory. Default: {DEFAULT_STORAGE_DIR}.",
    )
    parser.add_argument(
        "--max-date",
        default=None,
        help="Only publish completed dates <= YYYY-MM-DD.",
    )
    parser.add_argument(
        "--min-completed-days",
        type=int,
        default=1,
        help="Do not publish until at least this many completed dates are available.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-materialize and re-run pipeline even if the same date range was already published.",
    )
    parser.add_argument(
        "--allow-quarantined-source",
        action="store_true",
        help="Forensic/debug only: allow reading a quarantined backfill prefix. Never use for product publish.",
    )
    parser.add_argument(
        "--no-run-pipeline",
        action="store_true",
        help="Only materialize local raw HH artifacts; do not run scripts/run_pipeline.py.",
    )
    parser.add_argument(
        "--reload-api",
        action="store_true",
        help="Call /v1/admin/reload-data after a successful pipeline run.",
    )
    parser.add_argument(
        "--direct-index",
        action="store_true",
        help=(
            "Before API reload, rebuild vacancy_snapshots and the MeiliSearch vacancies index "
            "directly with a longer task timeout. Useful for large backfill publishes."
        ),
    )
    parser.add_argument(
        "--meili-task-timeout-ms",
        type=int,
        default=int(os.environ.get("SKILLRA_MEILI_TASK_TIMEOUT_MS", "120000")),
        help="MeiliSearch task wait timeout for --direct-index.",
    )
    parser.add_argument(
        "--meili-task-interval-ms",
        type=int,
        default=int(os.environ.get("SKILLRA_MEILI_TASK_INTERVAL_MS", "500")),
        help="MeiliSearch task polling interval for --direct-index.",
    )
    parser.add_argument(
        "--direct-index-batch-size",
        type=int,
        default=int(os.environ.get("SKILLRA_DIRECT_INDEX_BATCH_SIZE", "500")),
        help="MeiliSearch document batch size for --direct-index.",
    )
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("SKILLRA_API_BASE_URL"),
        help="API base URL for --reload-api. Defaults to SKILLRA_API_BASE_URL.",
    )
    parser.add_argument(
        "--api-token",
        default=os.environ.get("SKILLRA_API_TOKEN"),
        help="Service token for --reload-api. Defaults to SKILLRA_API_TOKEN.",
    )
    parser.add_argument(
        "--admin-token",
        default=os.environ.get("SKILLRA_ADMIN_TOKEN"),
        help="Admin token for --reload-api. Defaults to SKILLRA_ADMIN_TOKEN.",
    )
    parser.add_argument(
        "--sync-processed",
        action="store_true",
        help="Run scripts/s3_sync_processed.py after a successful pipeline run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned publish without downloading, writing, running pipeline, or reloading API.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_date(value: str, *, label: str) -> date:
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError as exc:
        raise SystemExit(f"{label} must be YYYY-MM-DD, got {value!r}") from exc


def require_non_empty(value: str | None, *, name: str) -> str:
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def safe_run_id(first_date: str, last_date: str) -> str:
    return f"backfill-completed-{first_date}_{last_date}"


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def load_json_bytes(payload: bytes, *, label: str) -> dict[str, Any]:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def download_json(client: Any, bucket: str, key: str) -> dict[str, Any]:
    return load_json_bytes(download_bytes(client, bucket, key), label=f"s3://{bucket}/{key}")


def s3_object_exists(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001 - boto3/MinIO clients vary by installed transport
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        message = str(exc)
        if "404" in message or "Not Found" in message or "NoSuchKey" in message:
            return False
        raise
    return True


def load_quarantine_marker(client: Any, bucket: str, prefix: str) -> dict[str, Any] | None:
    marker_key = f"{prefix.rstrip('/')}/_QUARANTINE.json"
    flag_key = f"{prefix.rstrip('/')}/QUARANTINED"
    if s3_object_exists(client, bucket, marker_key):
        return download_json(client, bucket, marker_key)
    if s3_object_exists(client, bucket, flag_key):
        return {
            "status": "quarantined",
            "marker_key": flag_key,
            "reason": "QUARANTINED marker exists without _QUARANTINE.json payload",
        }
    return None


def assert_not_quarantined(
    client: Any,
    bucket: str,
    prefix: str,
    *,
    allow_quarantined_source: bool,
) -> dict[str, Any] | None:
    marker = load_quarantine_marker(client, bucket, prefix)
    if marker is None:
        return None
    if allow_quarantined_source:
        return marker
    reason = marker.get("reason") or "quarantine marker exists"
    raise SystemExit(
        f"Refusing to publish quarantined source s3://{bucket}/{prefix.rstrip('/')}/: {reason}. "
        "Use --allow-quarantined-source only for forensic/debug reads, not product publish."
    )


def atomic_replace_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(payload, encoding="utf-8")
    os.replace(temp, path)


def write_delta_csv(path: Path, new_ids: Iterable[str], removed_ids: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["vacancy_id", "change"])
            for vacancy_id in sorted(new_ids):
                writer.writerow([vacancy_id, "new"])
            for vacancy_id in sorted(removed_ids):
                writer.writerow([vacancy_id, "removed"])
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def publish_lock(storage_dir: Path):
    storage_dir.mkdir(parents=True, exist_ok=True)
    lock_path = storage_dir / ".publish.lock"
    with lock_path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(f"Another backfill publish process holds lock: {lock_path}") from exc
        handle.write(f"pid={os.getpid()} updated_at_utc={utc_now()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_backfill_selection(
    client: Any,
    *,
    bucket: str,
    backfill_id: str,
    max_date: str | None,
    min_completed_days: int,
    allow_quarantined_source: bool = False,
) -> PublishSelection:
    prefix = f"backfills/{backfill_id}/"
    quarantine = assert_not_quarantined(
        client,
        bucket,
        prefix,
        allow_quarantined_source=allow_quarantined_source,
    )
    state = download_json(client, bucket, prefix + "state.json")
    completed_dates = sorted(str(value) for value in state.get("completed_dates") or [])
    if max_date is not None:
        max_day = parse_iso_date(max_date, label="--max-date")
        selected_dates = [
            value for value in completed_dates if parse_iso_date(value, label="completed date") <= max_day
        ]
    else:
        selected_dates = completed_dates
    if len(selected_dates) < min_completed_days:
        raise SystemExit(
            f"Only {len(selected_dates)} completed dates are available; " f"need at least {min_completed_days}."
        )
    if not selected_dates:
        raise SystemExit(f"No completed dates found in s3://{bucket}/{prefix}state.json")

    return PublishSelection(
        backfill_id=backfill_id,
        bucket=bucket,
        prefix=prefix,
        completed_dates=completed_dates,
        selected_dates=selected_dates,
        current_date=state.get("current_date"),
        backfill_updated_at_utc=state.get("updated_at_utc"),
        quarantine=quarantine,
        source_capability_ref=state.get("source_capability_ref")
        if isinstance(state.get("source_capability_ref"), dict)
        else None,
        coverage_claim=state.get("coverage_claim")
        or (
            state.get("source_capability_ref", {}).get("coverage_claim")
            if isinstance(state.get("source_capability_ref"), dict)
            else None
        ),
        coverage_limitations=list(
            state.get("coverage_limitations")
            or (
                state.get("source_capability_ref", {}).get("coverage_limitations")
                if isinstance(state.get("source_capability_ref"), dict)
                else []
            )
            or []
        ),
        closed_archived_coverage=state.get("closed_archived_coverage")
        or (
            state.get("source_capability_ref", {}).get("closed_archived_coverage")
            if isinstance(state.get("source_capability_ref"), dict)
            else None
        ),
    )


def state_already_published(storage_dir: Path, selection: PublishSelection) -> bool:
    state_path = storage_dir / "state.json"
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    publish = state.get("backfill_publish") or {}
    return (
        publish.get("backfill_id") == selection.backfill_id
        and publish.get("selected_dates") == selection.selected_dates
        and publish.get("pipeline_status") == "success"
    )


def cache_paths(storage_dir: Path, backfill_id: str, day: str) -> tuple[Path, Path]:
    day_dir = storage_dir / "cache" / backfill_id / f"date={day}"
    return day_dir / "snapshot.csv", day_dir / "metadata.json"


def ensure_cached_day(
    client: Any,
    *,
    bucket: str,
    prefix: str,
    storage_dir: Path,
    backfill_id: str,
    day: str,
    allow_quarantined_source: bool = False,
) -> tuple[Path, dict[str, Any]]:
    snapshot_path, metadata_path = cache_paths(storage_dir, backfill_id, day)
    assert_not_quarantined(
        client,
        bucket,
        f"{prefix}date={day}/",
        allow_quarantined_source=allow_quarantined_source,
    )
    metadata_key = f"{prefix}date={day}/metadata.json"
    snapshot_key = f"{prefix}date={day}/snapshot.csv"
    metadata = download_json(client, bucket, metadata_key)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_replace_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    expected_sha = str(metadata.get("sha256") or "")
    if snapshot_path.exists() and expected_sha and compute_sha256(snapshot_path) == expected_sha:
        return snapshot_path, metadata

    temp = snapshot_path.with_suffix(".csv.tmp")
    try:
        get_file(client, bucket, snapshot_key, temp)
        if expected_sha:
            actual_sha = compute_sha256(temp)
            if actual_sha != expected_sha:
                raise RuntimeError(f"sha256 mismatch for s3://{bucket}/{snapshot_key}: {actual_sha} != {expected_sha}")
        os.replace(temp, snapshot_path)
    finally:
        if temp.exists():
            temp.unlink()

    return snapshot_path, metadata


def detect_id_column(headers: Iterable[str]) -> str:
    header_set = set(headers)
    for column in ID_COLUMNS:
        if column in header_set:
            return column
    raise RuntimeError(f"Cannot detect vacancy id column; expected one of {', '.join(ID_COLUMNS)}")


def build_union_header(paths: Iterable[Path]) -> list[str]:
    header: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for column in read_csv_columns(str(path)):
            if column and column not in seen:
                seen.add(column)
                header.append(column)
    for column in ("backfill_snapshot_date", "backfill_source_key"):
        if column not in seen:
            header.append(column)
    return header


def materialize_latest(
    *,
    storage_dir: Path,
    selection: PublishSelection,
    cached_snapshots: dict[str, Path],
    day_metadata: dict[str, dict[str, Any]],
) -> MaterializeResult:
    first_date = selection.selected_dates[0]
    last_date = selection.selected_dates[-1]
    run_id = safe_run_id(first_date, last_date)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise RuntimeError(f"Generated invalid run_id: {run_id}")

    snapshots_dir = storage_dir / "snapshots"
    deltas_dir = storage_dir / "deltas"
    parquet_dir = storage_dir / "snapshots_parquet" / f"date={last_date}"
    quality_dir = storage_dir / "quality"
    snapshot_path = snapshots_dir / f"snapshot_{run_id}.csv"
    latest_path = storage_dir / "latest.csv"
    parquet_snapshot_path = parquet_dir / f"snapshot_{run_id}.parquet"
    delta_path = deltas_dir / f"delta_{run_id}.csv"
    duplicate_report_path = quality_dir / f"backfill_duplicate_report_{run_id}.json"
    state_path = storage_dir / "state.json"

    selected_paths = [cached_snapshots[day] for day in selection.selected_dates]
    duplicate_report = build_cross_partition_duplicate_report(
        {day: cached_snapshots[day] for day in selection.selected_dates}
    )
    header = build_union_header(selected_paths)
    id_column = detect_id_column(header)

    previous_latest = storage_dir / "latest.csv.previous"
    if latest_path.exists():
        latest_previous_temp = latest_path.with_name("latest.csv.previous.tmp")
        latest_previous_temp.write_bytes(latest_path.read_bytes())
        os.replace(latest_previous_temp, previous_latest)

    temp_snapshot = snapshot_path.with_suffix(".csv.tmp")
    seen_ids: set[str] = set()
    input_rows = 0
    output_rows = 0
    skipped_missing_id = 0
    per_date_rows: dict[str, int] = {}

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    try:
        with temp_snapshot.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            for day in reversed(selection.selected_dates):
                path = cached_snapshots[day]
                day_rows = 0
                with path.open("r", encoding="utf-8", newline="") as source:
                    reader = csv.DictReader(source)
                    for row in reader:
                        input_rows += 1
                        day_rows += 1
                        vacancy_id = str(row.get(id_column) or "").strip()
                        if not vacancy_id:
                            skipped_missing_id += 1
                            continue
                        if vacancy_id in seen_ids:
                            continue
                        seen_ids.add(vacancy_id)
                        row["backfill_snapshot_date"] = day
                        row["backfill_source_key"] = f"{selection.prefix}date={day}/snapshot.csv"
                        writer.writerow(row)
                        output_rows += 1
                per_date_rows[day] = day_rows
        os.replace(temp_snapshot, snapshot_path)
    finally:
        if temp_snapshot.exists():
            temp_snapshot.unlink()

    latest_temp = latest_path.with_suffix(".csv.tmp")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_temp.write_bytes(snapshot_path.read_bytes())
    os.replace(latest_temp, latest_path)

    previous_ids: set[str] = set()
    if previous_latest.exists():
        previous_ids = read_vacancy_ids(str(previous_latest))
    current_ids = read_vacancy_ids(str(latest_path))
    new_ids, removed_ids = compute_delta(previous_ids, current_ids)
    write_delta_csv(delta_path, new_ids, removed_ids)

    write_parquet_snapshot(str(snapshot_path), str(parquet_snapshot_path), compression="zstd")
    quality_dir.mkdir(parents=True, exist_ok=True)
    atomic_replace_text(
        duplicate_report_path,
        json.dumps(duplicate_report, ensure_ascii=False, indent=2) + "\n",
    )
    date_semantics = evaluate_csv_date_semantics(
        snapshot_path,
        requested_date_from=first_date,
        requested_date_to=last_date,
        max_unknown_share=DATE_SEMANTICS_MAX_UNKNOWN_SHARE,
        max_out_of_window_share=DATE_SEMANTICS_MAX_OUT_OF_WINDOW_SHARE,
    )

    sha256 = compute_sha256(latest_path)
    metadata_scopes = {str(payload.get("dataset_scope") or "unknown"): 0 for payload in day_metadata.values()}
    for day, payload in day_metadata.items():
        metadata_scopes[str(payload.get("dataset_scope") or "unknown")] = metadata_scopes.get(
            str(payload.get("dataset_scope") or "unknown"), 0
        ) + int(payload.get("row_count") or per_date_rows.get(day, 0))
    dataset_scope = "all_vacancies"
    if metadata_scopes and set(metadata_scopes) == {"salary_disclosed"}:
        dataset_scope = "salary_disclosed"
    salary_only = dataset_scope == "salary_disclosed"

    dataset_semantic_type = resolve_dataset_semantic_type(selection, date_semantics)

    state_payload = {
        "last_run_id": run_id,
        "run_date": last_date,
        "snapshot_path": snapshot_path.relative_to(storage_dir).as_posix(),
        "delta_path": delta_path.relative_to(storage_dir).as_posix(),
        "parquet_snapshot_path": parquet_snapshot_path.relative_to(storage_dir).as_posix(),
        "latest_path": latest_path.relative_to(storage_dir).as_posix(),
        "sha256": sha256,
        "row_count": output_rows,
        "new_count": len(new_ids),
        "removed_count": len(removed_ids),
        "generated_at_utc": utc_now(),
        "query": "minio_backfill_completed",
        "limit": None,
        "salary_only": salary_only,
        "dataset_scope": dataset_scope,
        "schema_version": SCHEMA_VERSION,
        "source_mode": "minio_backfill_completed",
        "source_kind": "minio_backfill_completed",
        "source_capability_ref": selection.source_capability_ref,
        "coverage_claim": selection.coverage_claim,
        "coverage_limitations": selection.coverage_limitations,
        "closed_archived_coverage": selection.closed_archived_coverage,
        "dataset_semantic_type": dataset_semantic_type,
        "requested_date_from": first_date,
        "requested_date_to": last_date,
        "observed_published_at_from": date_semantics.get("observed_published_at_from"),
        "observed_published_at_to": date_semantics.get("observed_published_at_to"),
        "date_semantics": date_semantics,
        "quarantine": selection.quarantine,
        "backfill_publish": {
            "backfill_id": selection.backfill_id,
            "bucket": selection.bucket,
            "prefix": selection.prefix,
            "selected_dates": selection.selected_dates,
            "first_completed_date": first_date,
            "last_completed_date": last_date,
            "completed_dates_available": selection.completed_dates,
            "current_date_excluded": selection.current_date,
            "backfill_updated_at_utc": selection.backfill_updated_at_utc,
            "input_rows": input_rows,
            "output_rows": output_rows,
            "duplicate_rows": input_rows - output_rows - skipped_missing_id,
            "skipped_missing_id": skipped_missing_id,
            "per_date_rows": per_date_rows,
            "cross_partition_duplicate_report": duplicate_report,
            "cross_partition_duplicate_report_path": duplicate_report_path.relative_to(storage_dir).as_posix(),
            "metadata_scope_rows": metadata_scopes,
            "pipeline_status": "pending",
        },
    }
    write_state_json(str(state_path), state_payload)

    manifest_payload = build_manifest_payload(
        state_payload=state_payload,
        duration_sec=0.0,
        parquet_snapshot_path=state_payload["parquet_snapshot_path"],
        snapshot_csv_path=state_payload["snapshot_path"],
        columns=header,
        schema_version=SCHEMA_VERSION,
    )
    append_manifest_jsonl(str(storage_dir / "manifest.jsonl"), manifest_payload)

    return MaterializeResult(
        input_rows=input_rows,
        output_rows=output_rows,
        duplicate_rows=input_rows - output_rows - skipped_missing_id,
        skipped_missing_id=skipped_missing_id,
        per_date_rows=per_date_rows,
        snapshot_path=snapshot_path,
        latest_path=latest_path,
        parquet_snapshot_path=parquet_snapshot_path,
        delta_path=delta_path,
        state_path=state_path,
        duplicate_report_path=duplicate_report_path,
        date_semantics=date_semantics,
        run_id=run_id,
        selected_dates=selection.selected_dates,
    )


def update_pipeline_status(state_path: Path, status: str, *, error: str | None = None) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    publish = dict(state.get("backfill_publish") or {})
    publish["pipeline_status"] = status
    publish["pipeline_status_updated_at_utc"] = utc_now()
    if error:
        publish["pipeline_error"] = error
    else:
        publish.pop("pipeline_error", None)
    state["backfill_publish"] = publish
    write_state_json(str(state_path), state)


def validate_materialized_raw(storage_dir: Path, state_path: Path) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    result = validate_local_raw_hh(
        storage_dir,
        state,
        min_rows=DEFAULT_MIN_ROWS,
        max_removed_share=1.0,
    )
    if result.get("status") != "passed":
        failures = ", ".join(str(item) for item in result.get("failures") or [])
        raise RuntimeError(f"Materialized raw HH validation failed: {failures}")
    return result


def run_subprocess(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def run_pipeline(result: MaterializeResult) -> None:
    run_subprocess(
        [
            sys.executable,
            "scripts/run_pipeline.py",
            "--raw-data-file",
            str(result.latest_path),
            "--dataset-meta-extra",
            str(result.state_path),
            "--run-id",
            result.run_id,
        ]
    )


def datetime_to_iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def vacancy_snapshot_to_document(snapshot: Any) -> dict[str, Any]:
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
        "published_at": datetime_to_iso(snapshot.published_at),
        "indexed_at": datetime_to_iso(snapshot.indexed_at),
        "dataset_run_id": snapshot.dataset_run_id,
    }


async def replace_vacancy_snapshots_from_latest(dataset_run_id: str) -> tuple[Any, list[dict[str, Any]], int]:
    import pandas as pd  # noqa: PLC0415
    from sqlalchemy import delete  # noqa: PLC0415

    from skillra_api.config import get_settings  # noqa: PLC0415
    from skillra_api.db import create_async_engine_from_settings, create_session_maker  # noqa: PLC0415
    from skillra_api.db.models import VacancySnapshot  # noqa: PLC0415
    from skillra_api.services.vacancy_indexer import _insert_snapshots, _snapshots_from_df  # noqa: PLC0415

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for --direct-index")
    features_path = Path(settings.features_path)
    if not features_path.exists():
        raise FileNotFoundError(f"Missing features parquet: {features_path}")

    features_df = pd.read_parquet(features_path)
    snapshots = _snapshots_from_df(features_df, dataset_run_id=dataset_run_id)
    documents = [vacancy_snapshot_to_document(snapshot) for snapshot in snapshots]

    engine = create_async_engine_from_settings(settings)
    session_maker = create_session_maker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            await session.execute(delete(VacancySnapshot))
            inserted = await _insert_snapshots(session, snapshots)
            await session.commit()
    finally:
        await engine.dispose()

    return settings, documents, inserted


async def record_direct_indexer_success(
    settings: Any,
    *,
    dataset_run_id: str,
    inserted: int,
    indexed: int,
) -> None:
    from skillra_api.db import create_async_engine_from_settings, create_session_maker  # noqa: PLC0415
    from skillra_api.db.models import IndexerRun  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    engine = create_async_engine_from_settings(settings)
    session_maker = create_session_maker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            session.add(
                IndexerRun(
                    started_at=now,
                    finished_at=now,
                    status="success",
                    source="direct_backfill_publish",
                    dataset_run_id=dataset_run_id,
                    inserted=inserted,
                    indexed=indexed,
                    error_msg=None,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


def meili_request(
    *,
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: Any | None = None,
    ignore_404: bool = False,
) -> dict[str, Any] | None:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if ignore_404 and exc.code == 404:
            return None
        raise RuntimeError(f"MeiliSearch {method} {path} returned HTTP {exc.code}: {body}") from exc
    if not body:
        return {}
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"MeiliSearch {method} {path} returned non-object JSON")
    return data


def task_uid(task: dict[str, Any] | None) -> int | str | None:
    if not task:
        return None
    return task.get("taskUid") or task.get("task_uid") or task.get("uid")


def wait_meili_task(
    *,
    base_url: str,
    api_key: str,
    task: dict[str, Any] | None,
    timeout_ms: int,
    interval_ms: int,
) -> dict[str, Any] | None:
    uid = task_uid(task)
    if uid is None:
        return None
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        result = meili_request(base_url=base_url, api_key=api_key, method="GET", path=f"/tasks/{uid}")
        status = str((result or {}).get("status") or "").lower()
        if status == "succeeded":
            return result
        if status in {"failed", "canceled", "cancelled"}:
            raise RuntimeError(f"MeiliSearch task {uid} ended with status {status}: {result}")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"MeiliSearch task {uid} did not finish in {timeout_ms}ms: {result}")
        time.sleep(max(interval_ms, 50) / 1000)


def rebuild_meili_vacancies_index(
    *,
    settings: Any,
    documents: list[dict[str, Any]],
    timeout_ms: int,
    interval_ms: int,
    batch_size: int,
) -> int:
    from skillra_api.services.search import (  # noqa: PLC0415
        VACANCY_FILTERABLE_ATTRIBUTES,
        VACANCY_SEARCHABLE_ATTRIBUTES,
        VACANCY_SORTABLE_ATTRIBUTES,
    )

    if not settings.meilisearch_url:
        return 0
    if not settings.meilisearch_api_key:
        raise RuntimeError("MEILISEARCH_API_KEY is required for --direct-index")
    if batch_size <= 0:
        raise RuntimeError("--direct-index-batch-size must be > 0")

    base_url = settings.meilisearch_url
    api_key = settings.meilisearch_api_key
    wait_kwargs = {"base_url": base_url, "api_key": api_key, "timeout_ms": timeout_ms, "interval_ms": interval_ms}

    delete_task = meili_request(
        base_url=base_url,
        api_key=api_key,
        method="DELETE",
        path="/indexes/vacancies",
        ignore_404=True,
    )
    wait_meili_task(task=delete_task, **wait_kwargs)
    create_task = meili_request(
        base_url=base_url,
        api_key=api_key,
        method="POST",
        path="/indexes",
        payload={"uid": "vacancies", "primaryKey": "id"},
    )
    wait_meili_task(task=create_task, **wait_kwargs)

    settings_payloads = [
        ("searchable-attributes", VACANCY_SEARCHABLE_ATTRIBUTES),
        ("filterable-attributes", VACANCY_FILTERABLE_ATTRIBUTES),
        ("sortable-attributes", VACANCY_SORTABLE_ATTRIBUTES),
    ]
    for endpoint, payload in settings_payloads:
        task = meili_request(
            base_url=base_url,
            api_key=api_key,
            method="PUT",
            path=f"/indexes/vacancies/settings/{endpoint}",
            payload=payload,
        )
        wait_meili_task(task=task, **wait_kwargs)

    pagination_task = meili_request(
        base_url=base_url,
        api_key=api_key,
        method="PATCH",
        path="/indexes/vacancies/settings",
        payload={"pagination": {"maxTotalHits": max(50_000, len(documents) + 1_000)}},
    )
    wait_meili_task(task=pagination_task, **wait_kwargs)

    indexed = 0
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        task = meili_request(
            base_url=base_url,
            api_key=api_key,
            method="POST",
            path="/indexes/vacancies/documents?primaryKey=id",
            payload=batch,
        )
        wait_meili_task(task=task, **wait_kwargs)
        indexed += len(batch)

    stats = meili_request(base_url=base_url, api_key=api_key, method="GET", path="/indexes/vacancies/stats")
    total = int((stats or {}).get("numberOfDocuments") or 0)
    if total != len(documents):
        raise RuntimeError(f"MeiliSearch document count mismatch after direct index: {total} != {len(documents)}")
    return indexed


def direct_index_search(result: MaterializeResult, *, timeout_ms: int, interval_ms: int, batch_size: int) -> dict:
    settings, documents, inserted = asyncio.run(replace_vacancy_snapshots_from_latest(result.run_id))
    indexed = rebuild_meili_vacancies_index(
        settings=settings,
        documents=documents,
        timeout_ms=timeout_ms,
        interval_ms=interval_ms,
        batch_size=batch_size,
    )
    asyncio.run(
        record_direct_indexer_success(
            settings,
            dataset_run_id=result.run_id,
            inserted=inserted,
            indexed=indexed,
        )
    )
    return {"inserted": inserted, "indexed": indexed, "dataset_run_id": result.run_id}


def sync_processed() -> None:
    run_subprocess([sys.executable, "scripts/s3_sync_processed.py"])


def reload_api(*, api_base_url: str, api_token: str, admin_token: str) -> dict[str, Any]:
    url = api_base_url.rstrip("/") + "/v1/admin/reload-data"
    request = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Skillra-Token": api_token,
            "X-Admin-Token": admin_token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"reload-data returned HTTP {exc.code}: {body}") from exc
    if status < 200 or status >= 300:
        raise RuntimeError(f"reload-data returned HTTP {status}: {payload!r}")
    if not payload:
        return {"status": "empty"}
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("reload-data response is not a JSON object")
    return data


def update_data_run_state(
    *,
    api_base_url: str,
    api_token: str,
    admin_token: str,
    run_id: str,
    state: str,
    raw_rows: int | None = None,
    processed_rows: int | None = None,
) -> dict[str, Any]:
    url = api_base_url.rstrip("/") + f"/v1/admin/data-runs/{run_id}/state"
    payload: dict[str, Any] = {"state": state, "source": "backfill_publish"}
    if raw_rows is not None:
        payload["raw_rows"] = raw_rows
    if processed_rows is not None:
        payload["processed_rows"] = processed_rows
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "X-Skillra-Token": api_token,
            "X-Admin-Token": admin_token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"data-runs state update returned HTTP {exc.code}: {body}") from exc
    if status < 200 or status >= 300:
        raise RuntimeError(f"data-runs state update returned HTTP {status}: {body!r}")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("data-runs state update response is not a JSON object")
    return data


def main() -> None:
    args = parse_args()
    backfill_id = require_non_empty(args.backfill_id, name="--backfill-id or SKILLRA_HH_BACKFILL_ID")
    bucket = require_non_empty(args.bucket, name="--bucket or S3_BUCKET_RAW_HH")
    storage_dir = args.storage_dir

    if args.reload_api:
        require_non_empty(args.api_base_url, name="--api-base-url or SKILLRA_API_BASE_URL")
        require_non_empty(args.api_token, name="--api-token or SKILLRA_API_TOKEN")
        require_non_empty(args.admin_token, name="--admin-token or SKILLRA_ADMIN_TOKEN")

    client = create_s3_client(os.environ)
    with publish_lock(storage_dir):
        selection = load_backfill_selection(
            client,
            bucket=bucket,
            backfill_id=backfill_id,
            max_date=args.max_date,
            min_completed_days=args.min_completed_days,
            allow_quarantined_source=args.allow_quarantined_source,
        )
        planned = {
            "backfill_id": selection.backfill_id,
            "bucket": selection.bucket,
            "selected_dates": selection.selected_dates,
            "current_date_excluded": selection.current_date,
            "run_id": safe_run_id(selection.selected_dates[0], selection.selected_dates[-1]),
            "storage_dir": str(storage_dir),
        }
        if args.dry_run:
            print(json.dumps({"status": "planned", **planned}, ensure_ascii=False, indent=2))
            return
        if state_already_published(storage_dir, selection) and not args.force:
            print(json.dumps({"status": "skipped_unchanged", **planned}, ensure_ascii=False, indent=2))
            return

        started = time.monotonic()
        cached_snapshots: dict[str, Path] = {}
        day_metadata: dict[str, dict[str, Any]] = {}
        for day in selection.selected_dates:
            snapshot, metadata = ensure_cached_day(
                client,
                bucket=bucket,
                prefix=selection.prefix,
                storage_dir=storage_dir,
                backfill_id=selection.backfill_id,
                day=day,
                allow_quarantined_source=args.allow_quarantined_source,
            )
            cached_snapshots[day] = snapshot
            day_metadata[day] = metadata

        result = materialize_latest(
            storage_dir=storage_dir,
            selection=selection,
            cached_snapshots=cached_snapshots,
            day_metadata=day_metadata,
        )
        raw_gate = validate_materialized_raw(storage_dir, result.state_path)

        reload_result: dict[str, Any] | None = None
        data_run_result: dict[str, Any] | None = None
        direct_index_result: dict[str, Any] | None = None
        try:
            if not args.no_run_pipeline:
                run_pipeline(result)
                if args.sync_processed:
                    sync_processed()
                if args.direct_index:
                    direct_index_result = direct_index_search(
                        result,
                        timeout_ms=args.meili_task_timeout_ms,
                        interval_ms=args.meili_task_interval_ms,
                        batch_size=args.direct_index_batch_size,
                    )
                if args.reload_api:
                    reload_result = reload_api(
                        api_base_url=args.api_base_url,
                        api_token=args.api_token,
                        admin_token=args.admin_token,
                    )
                    dataset_meta = (reload_result.get("datastore") or {}).get("dataset_meta") or {}
                    processed_rows = dataset_meta.get("features_rows")
                    data_run_result = update_data_run_state(
                        api_base_url=args.api_base_url,
                        api_token=args.api_token,
                        admin_token=args.admin_token,
                        run_id=result.run_id,
                        state="published",
                        raw_rows=result.output_rows,
                        processed_rows=int(processed_rows) if processed_rows is not None else result.output_rows,
                    )
                update_pipeline_status(result.state_path, "success")
            else:
                update_pipeline_status(result.state_path, "materialized")
        except Exception as exc:
            update_pipeline_status(result.state_path, "failed", error=f"{exc.__class__.__name__}: {exc}")
            raise

        summary = {
            "status": "published",
            "run_id": result.run_id,
            "selected_dates": result.selected_dates,
            "input_rows": result.input_rows,
            "output_rows": result.output_rows,
            "duplicate_rows": result.duplicate_rows,
            "skipped_missing_id": result.skipped_missing_id,
            "duplicate_report_path": str(result.duplicate_report_path),
            "date_semantics": result.date_semantics,
            "latest_path": str(result.latest_path),
            "state_path": str(result.state_path),
            "raw_gate": raw_gate,
            "pipeline_ran": not args.no_run_pipeline,
            "direct_index": direct_index_result,
            "api_reloaded": reload_result is not None,
            "data_run": data_run_result,
            "reload_result": reload_result,
            "duration_sec": round(time.monotonic() - started, 2),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
