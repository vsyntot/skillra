from __future__ import annotations

"""Resumable HH historical backfill into MinIO/S3.

This job stores raw daily shards under ``backfills/<backfill_id>/...`` and does
not mutate production ``raw/latest`` or processed ``latest`` pointers.
"""

import argparse
import fcntl
import csv
import hashlib
import json
import os
import random
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parser import hh_scraper  # noqa: E402
from skillra_pda.ingest.date_semantics import evaluate_csv_date_semantics  # noqa: E402
from skillra_pda.ingest.source_registry import (  # noqa: E402
    source_capability_ref_from_report,
    validate_source_capability_ref,
)
from skillra_pda.storage.s3_client import create_s3_client, put_file, upload_bytes  # noqa: E402

DATE_FORMAT = "%Y-%m-%d"
DEFAULT_STORAGE_DIR = Path("data") / "raw" / "hh" / "backfill"
DATE_SEMANTICS_MAX_UNKNOWN_SHARE = 0.05
DATE_SEMANTICS_MAX_OUT_OF_WINDOW_SHARE = 0.0


class DateSemanticsError(RuntimeError):
    """Raised when HH historical backfill rows do not match the requested date."""


class SourceCapabilityError(RuntimeError):
    """Raised when historical collection starts without proven source capability."""


@dataclass(frozen=True)
class BackfillConfig:
    date_from: date
    date_to: date
    storage_dir: Path
    bucket: str
    backfill_id: str
    query: str = hh_scraper.DEFAULT_QUERY
    limit_per_day: int = 100_000
    delay: float = 1.5
    max_pages: int | None = None
    areas: tuple[int, ...] = tuple(hh_scraper.DEFAULT_AREA_IDS)
    salary_only: bool = False
    dataset_scope: str = "all_vacancies"
    retry_delay_seconds: int = 300
    max_attempts_per_day: int = 0
    partial_upload_pages: int = 5
    dry_run: bool = False
    source_capability_report: Path | None = None
    require_source_capability: bool = True


@dataclass
class BackfillState:
    backfill_id: str
    date_from: str
    date_to: str
    bucket: str
    completed_dates: list[str] = field(default_factory=list)
    failed_attempts: dict[str, int] = field(default_factory=dict)
    current_date: str | None = None
    current_area_id: int | None = None
    current_experience: str | None = None
    current_page: int | None = None
    current_rows: int = 0
    current_pages_completed: int = 0
    last_error: str | None = None
    updated_at_utc: str | None = None
    source_capability_ref: dict[str, Any] | None = None


@dataclass
class DayProgress:
    date: str
    area_index: int = 0
    experience_index: int = 0
    page: int = 0
    rows_written: int = 0
    pages_completed: int = 0
    search_pages_requested: int = 0
    vacancy_links_seen: int = 0
    vacancy_records_written: int = 0
    last_area_id: int | None = None
    last_experience: str | None = None
    last_page: int | None = None
    last_page_links: int = 0
    last_page_records: int = 0
    started_at_utc: str | None = None
    updated_at_utc: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", required=True, help="Start date, inclusive: YYYY-MM-DD.")
    parser.add_argument("--date-to", default="today", help="End date, inclusive: YYYY-MM-DD or today.")
    parser.add_argument("--storage-dir", type=Path, default=DEFAULT_STORAGE_DIR)
    parser.add_argument("--bucket", default=os.environ.get("S3_BUCKET_RAW_HH"))
    parser.add_argument("--backfill-id", default=None)
    parser.add_argument("--query", default=hh_scraper.DEFAULT_QUERY)
    parser.add_argument("--limit-per-day", type=int, default=100_000)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--areas", nargs="*", type=int, default=list(hh_scraper.DEFAULT_AREA_IDS))
    parser.add_argument("--salary-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dataset-scope", default=None)
    parser.add_argument(
        "--retry-delay-seconds",
        type=int,
        default=300,
        help="Sleep before retrying a failed day. Default: 300.",
    )
    parser.add_argument(
        "--max-attempts-per-day",
        type=int,
        default=0,
        help="0 means retry forever; useful in production systemd mode.",
    )
    parser.add_argument(
        "--partial-upload-pages",
        type=int,
        default=5,
        help="Upload snapshot.partial.csv to S3 every N completed search pages. 0 disables partial snapshots.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--source-capability-report",
        type=Path,
        default=Path(os.environ["SKILLRA_HH_SOURCE_CAPABILITY_REPORT"])
        if os.environ.get("SKILLRA_HH_SOURCE_CAPABILITY_REPORT")
        else None,
        help=(
            "JSON report produced by scripts/hh_source_capability_check.py for the requested historical window. "
            "Required unless --allow-unproven-source is passed."
        ),
    )
    parser.add_argument(
        "--allow-unproven-source",
        action="store_true",
        help="Explicit emergency/debug bypass for the source capability preflight. Do not use for product data.",
    )
    return parser.parse_args()


def parse_date(value: str) -> date:
    if value == "today":
        return datetime.now(timezone.utc).date()
    return datetime.strptime(value, DATE_FORMAT).date()


def default_backfill_id(date_from: date, date_to: date) -> str:
    return f"it-vacancies-{date_from.isoformat()}_{date_to.isoformat()}"


def config_from_args(args: argparse.Namespace) -> BackfillConfig:
    date_from = parse_date(args.date_from)
    date_to = parse_date(args.date_to)
    if date_to < date_from:
        raise SystemExit("--date-to must be greater than or equal to --date-from")
    if not args.bucket:
        raise SystemExit("S3 bucket not provided. Set S3_BUCKET_RAW_HH or pass --bucket.")
    dataset_scope = args.dataset_scope or ("salary_disclosed" if args.salary_only else "all_vacancies")
    return BackfillConfig(
        date_from=date_from,
        date_to=date_to,
        storage_dir=args.storage_dir,
        bucket=args.bucket,
        backfill_id=args.backfill_id or default_backfill_id(date_from, date_to),
        query=args.query,
        limit_per_day=args.limit_per_day,
        delay=args.delay,
        max_pages=args.max_pages,
        areas=tuple(args.areas),
        salary_only=args.salary_only,
        dataset_scope=dataset_scope,
        retry_delay_seconds=args.retry_delay_seconds,
        max_attempts_per_day=args.max_attempts_per_day,
        partial_upload_pages=args.partial_upload_pages,
        dry_run=args.dry_run,
        source_capability_report=args.source_capability_report,
        require_source_capability=not args.allow_unproven_source,
    )


def assert_source_capability(config: BackfillConfig) -> dict[str, Any] | None:
    if not config.require_source_capability:
        print(
            "[backfill] WARNING: source capability preflight bypassed via --allow-unproven-source; "
            "output must not be used for product publish without a later capability proof.",
            file=sys.stderr,
        )
        return None

    if config.source_capability_report is None:
        raise SystemExit(
            "Source capability report is required before HH historical backfill. "
            "Run scripts/hh_source_capability_check.py with --strict for the requested date window "
            "and pass --source-capability-report <report.json>."
        )
    if not config.source_capability_report.exists():
        raise SystemExit(f"Source capability report not found: {config.source_capability_report}")

    report = json.loads(config.source_capability_report.read_text(encoding="utf-8"))
    failures = validate_source_capability_report(report, config)
    if failures:
        details = "; ".join(failures)
        raise SystemExit(f"Source capability report does not allow this backfill: {details}")
    print(f"[backfill] Source capability preflight passed: {config.source_capability_report}")
    return source_capability_ref_from_report(report, report_path=config.source_capability_report)


def validate_source_capability_report(report: dict[str, Any], config: BackfillConfig) -> list[str]:
    failures: list[str] = []
    source_ref = source_capability_ref_from_report(report, report_path=config.source_capability_report)
    failures.extend(
        "source_capability_ref: " + failure
        for failure in validate_source_capability_ref(
            source_ref,
            expected_source_mode="hh_html",
            expected_use_case="historical_collection",
            expected_dataset_scope=config.dataset_scope,
            expected_salary_only=config.salary_only,
            expected_areas=config.areas,
            require_supported=True,
        )
    )
    if report.get("capability_status") != "supported":
        failures.append(f"capability_status is {report.get('capability_status')!r}, expected 'supported'")
    if report.get("source_mode") != "hh_html":
        failures.append(f"source_mode is {report.get('source_mode')!r}, expected 'hh_html'")
    if int(report.get("row_count") or 0) <= 0:
        failures.append("row_count must be positive")
    if str(report.get("requested_query") or "") != config.query:
        failures.append("requested_query does not match backfill query")

    report_from = _report_date(report.get("requested_date_from"), "requested_date_from", failures)
    report_to = _report_date(report.get("requested_date_to"), "requested_date_to", failures)
    if report_from and report_from > config.date_from:
        failures.append(f"report starts at {report_from.isoformat()}, after backfill date_from {config.date_from}")
    if report_to and report_to < config.date_to:
        failures.append(f"report ends at {report_to.isoformat()}, before backfill date_to {config.date_to}")

    report_areas = {int(area) for area in report.get("areas") or []}
    missing_areas = sorted(set(config.areas) - report_areas)
    if missing_areas:
        failures.append("report areas do not cover backfill areas: " + ", ".join(str(area) for area in missing_areas))

    report_scope = report.get("dataset_scope")
    if report_scope is not None and report_scope != config.dataset_scope:
        failures.append(f"dataset_scope is {report_scope!r}, expected {config.dataset_scope!r}")
    report_salary_only = report.get("salary_only")
    if report_salary_only is not None and bool(report_salary_only) != config.salary_only:
        failures.append(f"salary_only is {bool(report_salary_only)!r}, expected {config.salary_only!r}")

    date_semantics = report.get("date_semantics")
    if not isinstance(date_semantics, dict) or date_semantics.get("status") != "passed":
        failures.append("date_semantics.status must be 'passed'")
    return failures


def _report_date(value: object, field_name: str, failures: list[str]) -> date | None:
    try:
        return parse_date(str(value))
    except Exception:  # noqa: BLE001 - report validation should return all actionable failures
        failures.append(f"{field_name} is not a valid YYYY-MM-DD date: {value!r}")
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_or_init_state(config: BackfillConfig) -> BackfillState:
    state_path = state_file(config)
    if not state_path.exists():
        return BackfillState(
            backfill_id=config.backfill_id,
            date_from=config.date_from.isoformat(),
            date_to=config.date_to.isoformat(),
            bucket=config.bucket,
            updated_at_utc=utc_now(),
        )
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return BackfillState(
        backfill_id=str(payload["backfill_id"]),
        date_from=str(payload["date_from"]),
        date_to=str(payload["date_to"]),
        bucket=str(payload["bucket"]),
        completed_dates=list(payload.get("completed_dates") or []),
        failed_attempts=dict(payload.get("failed_attempts") or {}),
        current_date=payload.get("current_date"),
        current_area_id=payload.get("current_area_id"),
        current_experience=payload.get("current_experience"),
        current_page=payload.get("current_page"),
        current_rows=int(payload.get("current_rows") or 0),
        current_pages_completed=int(payload.get("current_pages_completed") or 0),
        last_error=payload.get("last_error"),
        updated_at_utc=payload.get("updated_at_utc"),
        source_capability_ref=payload.get("source_capability_ref")
        if isinstance(payload.get("source_capability_ref"), dict)
        else None,
    )


def save_state(config: BackfillConfig, state: BackfillState) -> None:
    state.updated_at_utc = utc_now()
    if config.dry_run:
        print(f"[dry-run] write {state_file(config)}")
        return
    atomic_write_json(state_file(config), asdict(state))


def state_file(config: BackfillConfig) -> Path:
    return config.storage_dir / config.backfill_id / "state.json"


def manifest_file(config: BackfillConfig) -> Path:
    return config.storage_dir / config.backfill_id / "manifest.jsonl"


def progress_file(config: BackfillConfig, day: date) -> Path:
    return day_dir(config, day) / "progress.json"


def lock_file(config: BackfillConfig) -> Path:
    return config.storage_dir / config.backfill_id / ".lock"


@contextmanager
def backfill_lock(config: BackfillConfig):
    path = lock_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(f"Another backfill process already holds lock: {path}") from exc
        handle.write(f"pid={os.getpid()} updated_at_utc={utc_now()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def next_pending_date(config: BackfillConfig, state: BackfillState) -> date | None:
    completed = set(state.completed_dates)
    for day in date_range(config.date_from, config.date_to):
        if day.isoformat() not in completed:
            return day
    return None


def day_dir(config: BackfillConfig, day: date) -> Path:
    return config.storage_dir / config.backfill_id / f"date={day.isoformat()}"


def snapshot_path(config: BackfillConfig, day: date) -> Path:
    return day_dir(config, day) / "snapshot.csv"


def partial_snapshot_path(config: BackfillConfig, day: date) -> Path:
    return day_dir(config, day) / "snapshot.csv.tmp"


def metadata_path(config: BackfillConfig, day: date) -> Path:
    return day_dir(config, day) / "metadata.json"


def root_quarantine_path(config: BackfillConfig) -> Path:
    return config.storage_dir / config.backfill_id / "_QUARANTINE.json"


def day_quarantine_path(config: BackfillConfig, day: date) -> Path:
    return day_dir(config, day) / "_QUARANTINE.json"


def hh_datetime_bounds(day: date) -> tuple[str, str]:
    return f"{day.isoformat()}T00:00:00", f"{day.isoformat()}T23:59:59"


def ensure_empty_snapshot(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(hh_scraper.VacancyRecord.__dataclass_fields__))
        writer.writeheader()


def ensure_streaming_snapshot(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(hh_scraper.VacancyRecord.__dataclass_fields__))
        writer.writeheader()


def read_existing_vacancy_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {str(row.get("vacancy_id") or "") for row in reader if row.get("vacancy_id")}


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_or_init_progress(config: BackfillConfig, day: date) -> DayProgress:
    path = progress_file(config, day)
    if not path.exists():
        return DayProgress(date=day.isoformat(), started_at_utc=utc_now(), updated_at_utc=utc_now())
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DayProgress(
        date=str(payload["date"]),
        area_index=int(payload.get("area_index") or 0),
        experience_index=int(payload.get("experience_index") or 0),
        page=int(payload.get("page") or 0),
        rows_written=int(payload.get("rows_written") or 0),
        pages_completed=int(payload.get("pages_completed") or 0),
        search_pages_requested=int(payload.get("search_pages_requested") or 0),
        vacancy_links_seen=int(payload.get("vacancy_links_seen") or 0),
        vacancy_records_written=int(payload.get("vacancy_records_written") or 0),
        last_area_id=payload.get("last_area_id"),
        last_experience=payload.get("last_experience"),
        last_page=payload.get("last_page"),
        last_page_links=int(payload.get("last_page_links") or 0),
        last_page_records=int(payload.get("last_page_records") or 0),
        started_at_utc=payload.get("started_at_utc") or utc_now(),
        updated_at_utc=payload.get("updated_at_utc"),
    )


def save_progress(config: BackfillConfig, progress: DayProgress, day: date) -> None:
    progress.updated_at_utc = utc_now()
    if config.dry_run:
        print(f"[dry-run] write {progress_file(config, day)}", flush=True)
        return
    atomic_write_json(progress_file(config, day), asdict(progress))


def sync_state_from_progress(
    state: BackfillState,
    config: BackfillConfig,
    day: date,
    progress: DayProgress,
) -> None:
    state.current_date = day.isoformat()
    state.current_area_id = config.areas[progress.area_index] if progress.area_index < len(config.areas) else None
    state.current_experience = (
        hh_scraper.EXPERIENCE_SHARDS[progress.experience_index]
        if progress.experience_index < len(hh_scraper.EXPERIENCE_SHARDS)
        else None
    )
    state.current_page = progress.page
    state.current_rows = progress.rows_written
    state.current_pages_completed = progress.pages_completed


def advance_shard(progress: DayProgress) -> None:
    progress.page = 0
    progress.experience_index += 1
    if progress.experience_index >= len(hh_scraper.EXPERIENCE_SHARDS):
        progress.experience_index = 0
        progress.area_index += 1


def upload_backfill_state(config: BackfillConfig, client: Any) -> None:
    state_key = f"backfills/{config.backfill_id}/state.json"
    if config.dry_run:
        print(f"[dry-run] upload s3://{config.bucket}/{state_key}", flush=True)
        return
    upload_bytes(
        client,
        config.bucket,
        state_key,
        state_file(config).read_bytes(),
        content_type="application/json",
    )


def write_quarantine_markers(
    config: BackfillConfig,
    client: Any | None,
    *,
    day: date,
    reason: str,
    evidence: dict[str, Any],
) -> None:
    marker = {
        "status": "quarantined",
        "backfill_id": config.backfill_id,
        "bucket": config.bucket,
        "date": day.isoformat(),
        "reason": reason,
        "evidence": evidence,
        "source_params": {
            "query": config.query,
            "date_from": hh_datetime_bounds(day)[0],
            "date_to": hh_datetime_bounds(day)[1],
            "areas": list(config.areas),
            "salary_only": config.salary_only,
            "dataset_scope": config.dataset_scope,
        },
        "resume_policy": (
            "Do not resume this backfill id. Keep artifacts for forensic analysis only; "
            "start a new source after source capability and date-semantics gates pass."
        ),
        "created_at_utc": utc_now(),
    }
    marker_bytes = (json.dumps(marker, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    flag_bytes = b"quarantined\n"
    targets = [
        (
            root_quarantine_path(config),
            f"backfills/{config.backfill_id}/_QUARANTINE.json",
            marker_bytes,
            "application/json",
        ),
        (
            config.storage_dir / config.backfill_id / "QUARANTINED",
            f"backfills/{config.backfill_id}/QUARANTINED",
            flag_bytes,
            "text/plain",
        ),
        (
            day_quarantine_path(config, day),
            f"backfills/{config.backfill_id}/date={day.isoformat()}/_QUARANTINE.json",
            marker_bytes,
            "application/json",
        ),
        (
            day_dir(config, day) / "QUARANTINED",
            f"backfills/{config.backfill_id}/date={day.isoformat()}/QUARANTINED",
            flag_bytes,
            "text/plain",
        ),
    ]
    for local_path, key, payload, content_type in targets:
        if config.dry_run:
            print(f"[dry-run] write quarantine marker {local_path}", flush=True)
            print(f"[dry-run] upload s3://{config.bucket}/{key}", flush=True)
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payload)
        if client is not None:
            upload_bytes(client, config.bucket, key, payload, content_type=content_type)


def ensure_day_date_semantics_passed(
    config: BackfillConfig,
    client: Any | None,
    day: date,
    metadata: dict[str, Any],
) -> None:
    date_semantics = metadata.get("date_semantics")
    if isinstance(date_semantics, dict) and date_semantics.get("status") == "passed":
        return
    evidence = date_semantics if isinstance(date_semantics, dict) else {"status": "failed"}
    write_quarantine_markers(
        config,
        client,
        day=day,
        reason="historical date semantics gate failed",
        evidence=evidence,
    )
    failures = "; ".join(str(item) for item in evidence.get("failures") or [])
    raise DateSemanticsError(f"historical date semantics gate failed for {day.isoformat()}: {failures}")


def upload_day_progress(
    config: BackfillConfig,
    client: Any,
    day: date,
    *,
    include_partial_snapshot: bool,
) -> None:
    prefix = f"backfills/{config.backfill_id}/date={day.isoformat()}"
    progress_key = f"{prefix}/progress.json"
    partial_key = f"{prefix}/snapshot.partial.csv"
    if config.dry_run:
        print(f"[dry-run] upload s3://{config.bucket}/{progress_key}", flush=True)
        if include_partial_snapshot:
            print(f"[dry-run] upload s3://{config.bucket}/{partial_key}", flush=True)
        return
    put_file(client, config.bucket, progress_key, progress_file(config, day), content_type="application/json")
    if include_partial_snapshot and partial_snapshot_path(config, day).exists():
        put_file(client, config.bucket, partial_key, partial_snapshot_path(config, day), content_type="text/csv")


def save_page_checkpoint(
    config: BackfillConfig,
    state: BackfillState,
    client: Any | None,
    day: date,
    progress: DayProgress,
    *,
    include_partial_snapshot: bool = False,
) -> None:
    sync_state_from_progress(state, config, day, progress)
    save_state(config, state)
    save_progress(config, progress, day)
    if client is not None:
        upload_backfill_state(config, client)
        upload_day_progress(config, client, day, include_partial_snapshot=include_partial_snapshot)


def collect_day(
    config: BackfillConfig,
    day: date,
    state: BackfillState,
    client: Any | None,
) -> dict[str, Any]:
    output = snapshot_path(config, day)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        print(f"[backfill] Reusing local snapshot for {day.isoformat()}: {output}")
        metadata = build_day_metadata(config, day, output, started_at=None)
        if not config.dry_run:
            atomic_write_json(metadata_path(config, day), metadata)
        ensure_day_date_semantics_passed(config, client, day, metadata)
        return metadata

    temp = partial_snapshot_path(config, day)
    ensure_streaming_snapshot(temp)
    seen_vacancy_ids = read_existing_vacancy_ids(temp)
    progress = load_or_init_progress(config, day)
    progress.rows_written = len(seen_vacancy_ids)
    progress.vacancy_records_written = max(progress.vacancy_records_written, progress.rows_written)
    save_page_checkpoint(config, state, client, day, progress, include_partial_snapshot=False)

    date_from, date_to = hh_datetime_bounds(day)
    scraped_at = (
        datetime.fromisoformat(progress.started_at_utc) if progress.started_at_utc else datetime.now(timezone.utc)
    )
    employer_cache: dict[str, dict[str, object | None]] = {}
    proxy_index = progress.pages_completed

    with temp.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(hh_scraper.VacancyRecord.__dataclass_fields__))
        while progress.rows_written < config.limit_per_day and progress.area_index < len(config.areas):
            area_id = config.areas[progress.area_index]
            exp_filter = hh_scraper.EXPERIENCE_SHARDS[progress.experience_index]
            shard_label = exp_filter or "all_experience"

            if config.max_pages is not None and progress.page >= config.max_pages:
                print(
                    "[backfill] shard max-pages "
                    f"date={day.isoformat()} area={area_id} exp={shard_label} "
                    f"next_rows={progress.rows_written}",
                    flush=True,
                )
                advance_shard(progress)
                save_page_checkpoint(config, state, client, day, progress, include_partial_snapshot=False)
                continue

            page = progress.page
            headers = {
                "User-Agent": hh_scraper.pick_user_agent(),
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://hh.ru/",
            }
            params = hh_scraper.build_search_params(
                query=config.query,
                area_id=area_id,
                page=page,
                salary_only=config.salary_only,
                exp_filter=exp_filter,
                date_from=date_from,
                date_to=date_to,
            )
            session = hh_scraper.build_session(proxy=hh_scraper.rotate_proxy([], proxy_index))
            print(
                "[backfill] search "
                f"date={day.isoformat()} area={area_id} exp={shard_label} page={page} "
                f"rows={progress.rows_written}",
                flush=True,
            )
            try:
                search_response = session.get(hh_scraper.SEARCH_URL, params=params, headers=headers, timeout=20)
                progress.search_pages_requested += 1
                if search_response.status_code == 404:
                    print(
                        "[backfill] shard ended by 404 "
                        f"date={day.isoformat()} area={area_id} exp={shard_label} page={page}",
                        flush=True,
                    )
                    advance_shard(progress)
                    save_page_checkpoint(config, state, client, day, progress, include_partial_snapshot=False)
                    continue
                if search_response.status_code >= 400:
                    raise RuntimeError(
                        "HH search returned "
                        f"status={search_response.status_code} date={day.isoformat()} "
                        f"area={area_id} exp={shard_label} page={page}"
                    )

                links = hh_scraper.parse_search_page(search_response.text)
                progress.vacancy_links_seen += len(links)
                if not links:
                    print(
                        "[backfill] shard empty "
                        f"date={day.isoformat()} area={area_id} exp={shard_label} page={page} "
                        f"rows={progress.rows_written}",
                        flush=True,
                    )
                    advance_shard(progress)
                    save_page_checkpoint(config, state, client, day, progress, include_partial_snapshot=False)
                    continue

                page_records = 0
                for link in links:
                    headers["User-Agent"] = hh_scraper.pick_user_agent()
                    html = hh_scraper.fetch(session, link, headers=headers)
                    if not html:
                        print(f"[backfill] skip vacancy load_error url={link}", flush=True)
                        continue
                    record = hh_scraper.parse_vacancy_page(
                        html,
                        link,
                        area_id=area_id,
                        scraped_at=scraped_at,
                        require_salary=config.salary_only,
                        dataset_scope=config.dataset_scope,
                    )
                    if not record or record.vacancy_id in seen_vacancy_ids:
                        continue
                    seen_vacancy_ids.add(record.vacancy_id)
                    employer_url = record.employer_url
                    if employer_url and employer_url.startswith("/"):
                        employer_url = f"{hh_scraper.VACANCY_HOST}{employer_url}"
                        record.employer_url = employer_url
                    employer_info: dict[str, object | None] = {}
                    if employer_url:
                        if employer_url not in employer_cache:
                            emp_html = hh_scraper.fetch(session, employer_url, headers=headers)
                            employer_cache[employer_url] = hh_scraper.parse_employer_page(emp_html) if emp_html else {}
                        employer_info = employer_cache.get(employer_url, {})
                    hh_scraper.apply_employer_info(record, employer_info)
                    writer.writerow(record.to_dict())
                    progress.rows_written += 1
                    progress.vacancy_records_written = progress.rows_written
                    page_records += 1
                    handle.flush()
                    if progress.rows_written >= config.limit_per_day:
                        break
                    time.sleep(config.delay + random.uniform(0, config.delay))

                os.fsync(handle.fileno())
                progress.page = page + 1
                progress.pages_completed += 1
                progress.last_area_id = area_id
                progress.last_experience = exp_filter
                progress.last_page = page
                progress.last_page_links = len(links)
                progress.last_page_records = page_records
                include_partial = bool(
                    config.partial_upload_pages
                    and progress.pages_completed % config.partial_upload_pages == 0
                    and progress.rows_written > 0
                )
                save_page_checkpoint(
                    config,
                    state,
                    client,
                    day,
                    progress,
                    include_partial_snapshot=include_partial,
                )
                print(
                    "[backfill] page complete "
                    f"date={day.isoformat()} area={area_id} exp={shard_label} page={page} "
                    f"links={len(links)} new_records={page_records} total_rows={progress.rows_written}",
                    flush=True,
                )
                proxy_index += 1
                time.sleep(config.delay)
            finally:
                session.close()

    os.replace(temp, output)
    print(f"[backfill] Collected {day.isoformat()} into {output}", flush=True)
    metadata = build_day_metadata(config, day, output, started_at=progress.started_at_utc, progress=progress)
    if not config.dry_run:
        atomic_write_json(metadata_path(config, day), metadata)
    ensure_day_date_semantics_passed(config, client, day, metadata)
    return metadata


def build_day_metadata(
    config: BackfillConfig,
    day: date,
    output: Path,
    *,
    started_at: str | None,
    progress: DayProgress | None = None,
) -> dict[str, Any]:
    row_count = count_csv_rows(output)
    requested_from = day.isoformat()
    requested_to = day.isoformat()
    date_semantics = evaluate_csv_date_semantics(
        output,
        requested_date_from=requested_from,
        requested_date_to=requested_to,
        max_unknown_share=DATE_SEMANTICS_MAX_UNKNOWN_SHARE,
        max_out_of_window_share=DATE_SEMANTICS_MAX_OUT_OF_WINDOW_SHARE,
    )
    payload = {
        "backfill_id": config.backfill_id,
        "date": day.isoformat(),
        "date_from": hh_datetime_bounds(day)[0],
        "date_to": hh_datetime_bounds(day)[1],
        "requested_date_from": requested_from,
        "requested_date_to": requested_to,
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "query": config.query,
        "limit_per_day": config.limit_per_day,
        "row_count": row_count,
        "hit_limit": row_count >= config.limit_per_day,
        "sha256": compute_sha256(output),
        "dataset_scope": config.dataset_scope,
        "salary_only": config.salary_only,
        "areas": list(config.areas),
        "date_semantics": date_semantics,
    }
    if progress is not None:
        payload.update(
            {
                "pages_completed": progress.pages_completed,
                "search_pages_requested": progress.search_pages_requested,
                "vacancy_links_seen": progress.vacancy_links_seen,
            }
        )
    return payload


def upload_day(config: BackfillConfig, client: Any, day: date) -> dict[str, str]:
    prefix = f"backfills/{config.backfill_id}/date={day.isoformat()}"
    snapshot_key = f"{prefix}/snapshot.csv"
    metadata_key = f"{prefix}/metadata.json"
    if config.dry_run:
        print(f"[dry-run] upload s3://{config.bucket}/{snapshot_key}")
        print(f"[dry-run] upload s3://{config.bucket}/{metadata_key}")
        return {"snapshot_key": snapshot_key, "metadata_key": metadata_key}
    put_file(client, config.bucket, snapshot_key, snapshot_path(config, day), content_type="text/csv")
    put_file(client, config.bucket, metadata_key, metadata_path(config, day), content_type="application/json")
    return {"snapshot_key": snapshot_key, "metadata_key": metadata_key}


def upload_state_and_manifest(config: BackfillConfig, client: Any) -> None:
    state_key = f"backfills/{config.backfill_id}/state.json"
    manifest_key = f"backfills/{config.backfill_id}/manifest.jsonl"
    if config.dry_run:
        print(f"[dry-run] upload s3://{config.bucket}/{state_key}")
        print(f"[dry-run] upload s3://{config.bucket}/{manifest_key}")
        return
    upload_bytes(
        client,
        config.bucket,
        state_key,
        state_file(config).read_bytes(),
        content_type="application/json",
    )
    upload_bytes(
        client,
        config.bucket,
        manifest_key,
        manifest_file(config).read_bytes() if manifest_file(config).exists() else b"",
        content_type="application/x-ndjson",
    )


def mark_day_complete(
    config: BackfillConfig,
    state: BackfillState,
    client: Any,
    day: date,
    metadata: dict[str, Any],
    keys: dict[str, str],
) -> None:
    day_value = day.isoformat()
    if day_value not in state.completed_dates:
        state.completed_dates.append(day_value)
        state.completed_dates.sort()
    state.current_date = None
    state.current_area_id = None
    state.current_experience = None
    state.current_page = None
    state.current_rows = 0
    state.current_pages_completed = 0
    state.last_error = None
    save_state(config, state)
    manifest_payload = {
        "status": "success",
        "backfill_id": config.backfill_id,
        "date": day_value,
        "row_count": metadata["row_count"],
        "hit_limit": metadata["hit_limit"],
        **keys,
        "updated_at_utc": utc_now(),
    }
    if config.dry_run:
        print(f"[dry-run] append manifest: {manifest_payload}")
    else:
        append_jsonl(manifest_file(config), manifest_payload)
    upload_state_and_manifest(config, client)


def record_failure(config: BackfillConfig, state: BackfillState, day: date, exc: BaseException) -> int:
    day_value = day.isoformat()
    attempts = int(state.failed_attempts.get(day_value) or 0) + 1
    state.failed_attempts[day_value] = attempts
    state.current_date = day_value
    state.last_error = f"{exc.__class__.__name__}: {exc}"
    save_state(config, state)
    payload = {
        "status": "failed",
        "backfill_id": config.backfill_id,
        "date": day_value,
        "attempt": attempts,
        "error": state.last_error,
        "updated_at_utc": utc_now(),
    }
    if config.dry_run:
        print(f"[dry-run] append failure manifest: {payload}")
    else:
        append_jsonl(manifest_file(config), payload)
    return attempts


def run_backfill(config: BackfillConfig) -> None:
    with backfill_lock(config):
        run_backfill_locked(config)


def run_backfill_locked(config: BackfillConfig) -> None:
    source_capability_ref = assert_source_capability(config)
    state = load_or_init_state(config)
    if source_capability_ref is not None and state.source_capability_ref != source_capability_ref:
        state.source_capability_ref = source_capability_ref
        save_state(config, state)
    client = None if config.dry_run else create_s3_client(os.environ)
    if root_quarantine_path(config).exists():
        raise SystemExit(
            f"Backfill {config.backfill_id} is quarantined: {root_quarantine_path(config)}. "
            "Create a new backfill id after source capability gates pass."
        )

    while True:
        day = next_pending_date(config, state)
        if day is None:
            print(f"[backfill] Completed all dates for {config.backfill_id}")
            save_state(config, state)
            if client is not None:
                upload_state_and_manifest(config, client)
            return

        state.current_date = day.isoformat()
        save_state(config, state)
        if client is not None:
            upload_backfill_state(config, client)
        try:
            print(f"[backfill] Processing {day.isoformat()}")
            metadata = collect_day(config, day, state, client)
            keys = upload_day(config, client, day) if client is not None else upload_day(config, None, day)
            mark_day_complete(config, state, client, day, metadata, keys)
            print(f"[backfill] Completed {day.isoformat()} rows={metadata['row_count']}")
        except KeyboardInterrupt:
            raise
        except DateSemanticsError as exc:
            record_failure(config, state, day, exc)
            if client is not None:
                upload_backfill_state(config, client)
            raise
        except Exception as exc:  # noqa: BLE001 - production retry loop must persist state
            attempts = record_failure(config, state, day, exc)
            if config.max_attempts_per_day and attempts >= config.max_attempts_per_day:
                raise
            print(
                f"[backfill] Failed {day.isoformat()} attempt={attempts}: {exc}. "
                f"Retrying in {config.retry_delay_seconds}s.",
                file=sys.stderr,
            )
            time.sleep(config.retry_delay_seconds)


def main() -> None:
    run_backfill(config_from_args(parse_args()))


if __name__ == "__main__":
    main()
