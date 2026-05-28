from __future__ import annotations

"""Durable control-plane primitives for HH historical collection.

The module intentionally contains only source-agnostic planning/state logic.
It does not mutate raw/latest, processed/latest or Dataset Registry pointers.
"""

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

CONTROL_PLANE_SCHEMA_VERSION = 1
DEFAULT_MAX_FOUND_PER_SHARD = 1_800
DEFAULT_MAX_PAGES_PER_SHARD = 18
DEFAULT_MIN_TIME_WINDOW_MINUTES = 60

PLANNED_STATUSES = {"planned", "probing", "collecting", "validating"}
ACCEPTED_STATUSES = {"accepted", "accepted_empty"}
BLOCKING_STATUSES = {
    "blocked_source_capability",
    "blocked_source",
    "blocked_over_cap",
    "blocked_empty",
    "failed",
    "quarantined",
    "incomplete",
}


@dataclass
class HistoricalBackfillRuntimePolicy:
    search_concurrency: int = 4
    detail_concurrency: int = 16
    requests_per_second: float = 2.0
    retry_backoff_seconds: int = 300
    max_attempts_per_shard: int = 5
    circuit_breaker_failures: int = 3
    circuit_breaker_reset_seconds: int = 900

    def validate(self) -> list[str]:
        failures: list[str] = []
        if self.search_concurrency < 1:
            failures.append("search_concurrency must be >= 1")
        if self.detail_concurrency < 1:
            failures.append("detail_concurrency must be >= 1")
        if self.requests_per_second <= 0:
            failures.append("requests_per_second must be > 0")
        if self.max_attempts_per_shard < 1:
            failures.append("max_attempts_per_shard must be >= 1")
        return failures


@dataclass
class HistoricalBackfillPlanningConfig:
    backfill_id: str
    source_mode: str
    requested_date_from: date
    requested_date_to: date
    areas: tuple[int, ...] = (113,)
    professional_roles: tuple[str, ...] = ()
    experiences: tuple[str, ...] = ()
    schedules: tuple[str, ...] = ()
    employments: tuple[str, ...] = ()
    split_professional_roles: tuple[str, ...] = ()
    split_experiences: tuple[str, ...] = ()
    split_schedules: tuple[str, ...] = ()
    split_employments: tuple[str, ...] = ()
    dataset_scope: str = "all_vacancies"
    salary_only: bool = False
    coverage_claim: str = "unproven"
    coverage_limitations: tuple[str, ...] = ()
    closed_archived_coverage: str = "unproven"
    source_capability_ref: dict[str, Any] | None = None
    max_found_per_shard: int = DEFAULT_MAX_FOUND_PER_SHARD
    max_pages_per_shard: int = DEFAULT_MAX_PAGES_PER_SHARD
    min_time_window_minutes: int = DEFAULT_MIN_TIME_WINDOW_MINUTES
    runtime_policy: HistoricalBackfillRuntimePolicy = field(default_factory=HistoricalBackfillRuntimePolicy)

    def validate(self) -> list[str]:
        failures = self.runtime_policy.validate()
        if self.requested_date_to < self.requested_date_from:
            failures.append("requested_date_to must be >= requested_date_from")
        if not self.backfill_id:
            failures.append("backfill_id must be non-empty")
        if not self.source_mode:
            failures.append("source_mode must be non-empty")
        if not self.areas:
            failures.append("at least one area must be configured")
        if self.max_found_per_shard < 1:
            failures.append("max_found_per_shard must be >= 1")
        if self.max_pages_per_shard < 1:
            failures.append("max_pages_per_shard must be >= 1")
        if self.min_time_window_minutes < 1:
            failures.append("min_time_window_minutes must be >= 1")
        return failures


@dataclass
class HistoricalBackfillJob:
    backfill_id: str
    source_mode: str
    requested_date_from: str
    requested_date_to: str
    status: str = "planned"
    status_reason: str | None = None
    dataset_scope: str = "all_vacancies"
    salary_only: bool = False
    coverage_claim: str = "unproven"
    coverage_limitations: list[str] = field(default_factory=list)
    closed_archived_coverage: str = "unproven"
    source_capability_ref: dict[str, Any] | None = None
    shard_count: int = 0
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CONTROL_PLANE_SCHEMA_VERSION
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class HistoricalBackfillShard:
    shard_id: str
    backfill_id: str
    date_from: str
    date_to: str
    area_id: int
    professional_role: str | None = None
    experience: str | None = None
    schedule: str | None = None
    employment: str | None = None
    status: str = "planned"
    parent_shard_id: str | None = None
    split_level: int = 0
    found: int | None = None
    pages: int | None = None
    collected_rows: int = 0
    attempts: int = 0
    status_code_summary: dict[str, int] = field(default_factory=dict)
    output_keys: list[str] = field(default_factory=list)
    checksum: str | None = None
    expected_empty: bool = False
    empty_evidence: str | None = None
    failure_reason: str | None = None
    schema_version: int = CONTROL_PLANE_SCHEMA_VERSION
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class ShardObservation:
    shard_id: str
    found: int | None = None
    pages: int | None = None
    collected_rows: int = 0
    status_code_summary: dict[str, int] = field(default_factory=dict)
    output_keys: tuple[str, ...] = ()
    checksum: str | None = None
    expected_empty: bool = False
    empty_evidence: str | None = None
    errors: tuple[str, ...] = ()


def default_backfill_id(date_from: date, date_to: date, *, source_mode: str = "hh_api") -> str:
    return f"{source_mode}-historical-{date_from.isoformat()}_{date_to.isoformat()}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def plan_historical_backfill(
    config: HistoricalBackfillPlanningConfig,
) -> tuple[HistoricalBackfillJob, list[HistoricalBackfillShard]]:
    failures = config.validate()
    if failures:
        raise ValueError("; ".join(failures))
    shards: list[HistoricalBackfillShard] = []
    for window_from, window_to in iter_day_windows(config.requested_date_from, config.requested_date_to):
        for area_id in config.areas:
            for professional_role in _values_or_none(config.professional_roles):
                for experience in _values_or_none(config.experiences):
                    for schedule in _values_or_none(config.schedules):
                        for employment in _values_or_none(config.employments):
                            shards.append(
                                build_shard(
                                    backfill_id=config.backfill_id,
                                    date_from=window_from,
                                    date_to=window_to,
                                    area_id=area_id,
                                    professional_role=professional_role,
                                    experience=experience,
                                    schedule=schedule,
                                    employment=employment,
                                )
                            )
    job = HistoricalBackfillJob(
        backfill_id=config.backfill_id,
        source_mode=config.source_mode,
        requested_date_from=config.requested_date_from.isoformat(),
        requested_date_to=config.requested_date_to.isoformat(),
        dataset_scope=config.dataset_scope,
        salary_only=config.salary_only,
        coverage_claim=config.coverage_claim,
        coverage_limitations=list(config.coverage_limitations),
        closed_archived_coverage=config.closed_archived_coverage,
        source_capability_ref=config.source_capability_ref,
        shard_count=len(shards),
        runtime_policy=asdict(config.runtime_policy),
    )
    return job, shards


def iter_day_windows(date_from: date, date_to: date) -> Iterator[tuple[str, str]]:
    current = date_from
    while current <= date_to:
        start = datetime.combine(current, datetime.min.time())
        end = start + timedelta(days=1)
        yield _format_window(start), _format_window(end)
        current += timedelta(days=1)


def build_shard(
    *,
    backfill_id: str,
    date_from: str,
    date_to: str,
    area_id: int,
    professional_role: str | None = None,
    experience: str | None = None,
    schedule: str | None = None,
    employment: str | None = None,
    parent_shard_id: str | None = None,
    split_level: int = 0,
) -> HistoricalBackfillShard:
    payload = {
        "backfill_id": backfill_id,
        "date_from": date_from,
        "date_to": date_to,
        "area_id": area_id,
        "professional_role": professional_role,
        "experience": experience,
        "schedule": schedule,
        "employment": employment,
        "parent_shard_id": parent_shard_id,
        "split_level": split_level,
    }
    shard_id = (
        "shard-"
        + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
    )
    return HistoricalBackfillShard(
        shard_id=shard_id,
        backfill_id=backfill_id,
        date_from=date_from,
        date_to=date_to,
        area_id=area_id,
        professional_role=professional_role,
        experience=experience,
        schedule=schedule,
        employment=employment,
        parent_shard_id=parent_shard_id,
        split_level=split_level,
    )


def block_job_for_source_capability(
    job: HistoricalBackfillJob,
    shards: Sequence[HistoricalBackfillShard],
    *,
    reason: str,
) -> tuple[HistoricalBackfillJob, list[HistoricalBackfillShard]]:
    job.status = "blocked"
    job.status_reason = reason
    job.updated_at_utc = utc_now()
    blocked: list[HistoricalBackfillShard] = []
    for shard in shards:
        shard.status = "blocked_source_capability"
        shard.failure_reason = reason
        shard.updated_at_utc = job.updated_at_utc
        blocked.append(shard)
    return job, blocked


def apply_shard_observations(
    shards: Sequence[HistoricalBackfillShard],
    observations: Sequence[ShardObservation],
    config: HistoricalBackfillPlanningConfig,
) -> tuple[list[HistoricalBackfillShard], dict[str, Any]]:
    observations_by_id = {observation.shard_id: observation for observation in observations}
    output: list[HistoricalBackfillShard] = []
    split_children: list[HistoricalBackfillShard] = []
    summary = {
        "observed_shards": 0,
        "split_parents": 0,
        "new_child_shards": 0,
        "blocked_over_cap": 0,
        "blocked_source": 0,
        "accepted": 0,
        "accepted_empty": 0,
        "blocked_empty": 0,
    }
    for shard in shards:
        observation = observations_by_id.get(shard.shard_id)
        if observation is None:
            output.append(shard)
            continue
        summary["observed_shards"] += 1
        _apply_observation_fields(shard, observation)
        source_failure = _source_failure_reason(observation.errors, observation.status_code_summary)
        if source_failure is not None:
            shard.status = "blocked_source"
            shard.failure_reason = source_failure
            summary["blocked_source"] += 1
        elif shard_over_cap(observation, config):
            children = split_shard(shard, config)
            if children:
                shard.status = "split"
                shard.failure_reason = "split because result depth approaches source cap"
                split_children.extend(children)
                summary["split_parents"] += 1
                summary["new_child_shards"] += len(children)
            else:
                shard.status = "blocked_over_cap"
                shard.failure_reason = "shard exceeds source result-depth cap and cannot be split further"
                summary["blocked_over_cap"] += 1
        elif observation.collected_rows == 0:
            if observation.expected_empty:
                shard.status = "accepted_empty"
                summary["accepted_empty"] += 1
            else:
                shard.status = "blocked_empty"
                shard.failure_reason = "zero-row shard has no explicit empty-window evidence"
                summary["blocked_empty"] += 1
        else:
            shard.status = "accepted"
            summary["accepted"] += 1
        shard.updated_at_utc = utc_now()
        output.append(shard)
    output.extend(split_children)
    return output, summary


def shard_over_cap(observation: ShardObservation, config: HistoricalBackfillPlanningConfig) -> bool:
    found = observation.found if observation.found is not None else 0
    pages = observation.pages if observation.pages is not None else 0
    return found >= config.max_found_per_shard or pages >= config.max_pages_per_shard


def split_shard(
    shard: HistoricalBackfillShard,
    config: HistoricalBackfillPlanningConfig,
) -> list[HistoricalBackfillShard]:
    time_children = _split_by_time(shard, min_minutes=config.min_time_window_minutes)
    if time_children:
        return time_children
    for attr, values in (
        ("professional_role", config.split_professional_roles),
        ("experience", config.split_experiences),
        ("schedule", config.split_schedules),
        ("employment", config.split_employments),
    ):
        if getattr(shard, attr) is None and values:
            return [_clone_with_dimension(shard, attr, value) for value in values]
    return []


def summarize_backfill(job: HistoricalBackfillJob, shards: Sequence[HistoricalBackfillShard]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    rows = 0
    for shard in shards:
        statuses[shard.status] = statuses.get(shard.status, 0) + 1
        rows += int(shard.collected_rows or 0)
    blocking = sum(count for status, count in statuses.items() if status in BLOCKING_STATUSES)
    accepted = sum(count for status, count in statuses.items() if status in ACCEPTED_STATUSES)
    planned = sum(count for status, count in statuses.items() if status in PLANNED_STATUSES)
    return {
        "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        "backfill_id": job.backfill_id,
        "job_status": job.status,
        "job_status_reason": job.status_reason,
        "shard_count": len(shards),
        "status_counts": statuses,
        "accepted_shards": accepted,
        "planned_shards": planned,
        "blocking_shards": blocking,
        "collected_rows": rows,
        "coverage_claim": job.coverage_claim,
        "coverage_limitations": job.coverage_limitations,
        "closed_archived_coverage": job.closed_archived_coverage,
    }


class JsonBackfillStore:
    """Small durable state store for backfill job/shard snapshots."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def job_dir(self, backfill_id: str) -> Path:
        return self.root_dir / backfill_id

    def job_path(self, backfill_id: str) -> Path:
        return self.job_dir(backfill_id) / "job.json"

    def shards_path(self, backfill_id: str) -> Path:
        return self.job_dir(backfill_id) / "shards.jsonl"

    def summary_path(self, backfill_id: str) -> Path:
        return self.job_dir(backfill_id) / "summary.json"

    def lock_path(self, backfill_id: str) -> Path:
        return self.job_dir(backfill_id) / ".lock"

    @contextmanager
    def lock(self, backfill_id: str) -> Iterator[None]:
        self.job_dir(backfill_id).mkdir(parents=True, exist_ok=True)
        lock_path = self.lock_path(backfill_id)
        with lock_path.open("w", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(f"backfill {backfill_id!r} is already locked: {lock_path}") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def save_snapshot(
        self,
        job: HistoricalBackfillJob,
        shards: Sequence[HistoricalBackfillShard],
    ) -> dict[str, Any]:
        job.shard_count = len(shards)
        job.updated_at_utc = utc_now()
        job_dir = self.job_dir(job.backfill_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.job_path(job.backfill_id), asdict(job))
        _atomic_write_jsonl(self.shards_path(job.backfill_id), [asdict(shard) for shard in shards])
        summary = summarize_backfill(job, shards)
        _atomic_write_json(self.summary_path(job.backfill_id), summary)
        return summary

    def load_snapshot(self, backfill_id: str) -> tuple[HistoricalBackfillJob, list[HistoricalBackfillShard]]:
        job_payload = _read_json(self.job_path(backfill_id))
        job = HistoricalBackfillJob(**job_payload)
        shards = [HistoricalBackfillShard(**payload) for payload in _read_jsonl(self.shards_path(backfill_id))]
        return job, shards


class TokenBucketRateLimiter:
    """Deterministic token-bucket helper for worker runtimes."""

    def __init__(self, *, rate_per_second: float, capacity: float | None = None) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be > 0")
        self.rate_per_second = rate_per_second
        self.capacity = capacity if capacity is not None else max(1.0, rate_per_second)
        self.tokens = self.capacity
        self.updated_at = time.monotonic()

    def reserve(self, *, tokens: float = 1.0, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_second)
        self.updated_at = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return 0.0
        missing = tokens - self.tokens
        wait_seconds = missing / self.rate_per_second
        self.tokens = 0.0
        self.updated_at = now + wait_seconds
        return wait_seconds


class SourceCircuitBreaker:
    """Track repeated source-level failures and expose an open/closed state."""

    def __init__(self, *, failure_threshold: int = 3, reset_seconds: int = 900) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.failure_count = 0
        self.opened_at: float | None = None

    def record_success(self) -> None:
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self, *, now: float | None = None) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold and self.opened_at is None:
            self.opened_at = time.monotonic() if now is None else now

    def is_open(self, *, now: float | None = None) -> bool:
        if self.opened_at is None:
            return False
        now = time.monotonic() if now is None else now
        if now - self.opened_at >= self.reset_seconds:
            self.failure_count = 0
            self.opened_at = None
            return False
        return True


def _values_or_none(values: Sequence[str]) -> tuple[str | None, ...]:
    return tuple(values) if values else (None,)


def _format_window(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_window(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _split_by_time(shard: HistoricalBackfillShard, *, min_minutes: int) -> list[HistoricalBackfillShard]:
    start = _parse_window(shard.date_from)
    end = _parse_window(shard.date_to)
    duration = end - start
    if duration <= timedelta(minutes=min_minutes):
        return []
    mid = start + duration / 2
    return [
        build_shard(
            backfill_id=shard.backfill_id,
            date_from=_format_window(start),
            date_to=_format_window(mid),
            area_id=shard.area_id,
            professional_role=shard.professional_role,
            experience=shard.experience,
            schedule=shard.schedule,
            employment=shard.employment,
            parent_shard_id=shard.shard_id,
            split_level=shard.split_level + 1,
        ),
        build_shard(
            backfill_id=shard.backfill_id,
            date_from=_format_window(mid),
            date_to=_format_window(end),
            area_id=shard.area_id,
            professional_role=shard.professional_role,
            experience=shard.experience,
            schedule=shard.schedule,
            employment=shard.employment,
            parent_shard_id=shard.shard_id,
            split_level=shard.split_level + 1,
        ),
    ]


def _clone_with_dimension(
    shard: HistoricalBackfillShard,
    attr: str,
    value: str,
) -> HistoricalBackfillShard:
    kwargs = {
        "backfill_id": shard.backfill_id,
        "date_from": shard.date_from,
        "date_to": shard.date_to,
        "area_id": shard.area_id,
        "professional_role": shard.professional_role,
        "experience": shard.experience,
        "schedule": shard.schedule,
        "employment": shard.employment,
        "parent_shard_id": shard.shard_id,
        "split_level": shard.split_level + 1,
    }
    kwargs[attr] = value
    return build_shard(**kwargs)


def _apply_observation_fields(shard: HistoricalBackfillShard, observation: ShardObservation) -> None:
    shard.found = observation.found
    shard.pages = observation.pages
    shard.collected_rows = observation.collected_rows
    shard.status_code_summary = dict(observation.status_code_summary)
    shard.output_keys = list(observation.output_keys)
    shard.checksum = observation.checksum
    shard.expected_empty = observation.expected_empty
    shard.empty_evidence = observation.empty_evidence
    shard.attempts += 1


def _source_failure_reason(errors: Sequence[str], status_code_summary: dict[str, int]) -> str | None:
    lower_errors = " ".join(errors).lower()
    if any(token in lower_errors for token in ("captcha", "forbidden", "blocked", "429", "403")):
        return "source-level failure: " + lower_errors[:300]
    for code in ("403", "429"):
        if int(status_code_summary.get(code) or 0) > 0:
            return f"source-level HTTP {code} response observed"
    return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _atomic_write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temp, path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError(f"{path} contains a non-object JSONL row")
                rows.append(payload)
    return rows
