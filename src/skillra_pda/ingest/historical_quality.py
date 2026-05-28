from __future__ import annotations

"""Quality gates for historical HH backfill candidates."""

import csv
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from skillra_pda.ingest.historical_backfill_control import (
    ACCEPTED_STATUSES,
    BLOCKING_STATUSES,
    HistoricalBackfillJob,
    HistoricalBackfillPlanningConfig,
    HistoricalBackfillShard,
)
from skillra_pda.ingest.source_registry import validate_source_capability_ref


@dataclass(frozen=True)
class HistoricalQualityThresholds:
    max_unknown_published_at_share: float = 0.05
    max_out_of_window_share: float = 0.0
    max_duplicate_share: float = 0.05
    max_found_per_shard: int = 1_800
    max_pages_per_shard: int = 18


@dataclass
class HistoricalGateResult:
    status: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    shard_metrics: dict[str, Any] = field(default_factory=dict)
    duplicate_report: dict[str, Any] | None = None
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_historical_candidate(
    job: HistoricalBackfillJob,
    shards: Sequence[HistoricalBackfillShard],
    *,
    rows: Iterable[Mapping[str, Any]] | None = None,
    thresholds: HistoricalQualityThresholds | None = None,
) -> HistoricalGateResult:
    thresholds = thresholds or HistoricalQualityThresholds()
    failures: list[str] = []
    warnings: list[str] = []
    source_failures = validate_source_capability_ref(
        job.source_capability_ref,
        expected_use_case="historical_collection",
        expected_dataset_scope=job.dataset_scope,
        expected_salary_only=job.salary_only,
        require_supported=True,
    )
    failures.extend(f"source_capability_ref: {failure}" for failure in source_failures)

    if job.status in {"blocked", "quarantined", "failed"}:
        failures.append(f"job status is {job.status!r}: {job.status_reason or 'no reason'}")
    if job.coverage_claim in {"", "unproven", "unproven_source_access"}:
        failures.append(f"coverage_claim is not publishable: {job.coverage_claim!r}")
    if job.coverage_claim == "complete_hh_archive" and job.closed_archived_coverage != "included":
        failures.append("complete_hh_archive claim requires closed_archived_coverage=included")
    if job.coverage_claim == "retrievable_through_proven_source" and job.closed_archived_coverage != "included":
        warnings.append("coverage is source-retrievable, not a proven complete HH archive")

    shard_metrics = evaluate_shard_completeness(shards, thresholds=thresholds)
    failures.extend(shard_metrics["failures"])

    duplicate_report: dict[str, Any] | None = None
    if rows is not None:
        duplicate_report = duplicate_conflict_report(rows)
        if duplicate_report["conflict_count"] > 0:
            failures.append(f"duplicate conflicts detected: {duplicate_report['conflict_count']}")
        if duplicate_report["duplicate_share"] > thresholds.max_duplicate_share:
            failures.append(
                f"duplicate_share {duplicate_report['duplicate_share']} > "
                f"max_duplicate_share {thresholds.max_duplicate_share}"
            )

    return HistoricalGateResult(
        status="accepted" if not failures else "blocked",
        failures=failures,
        warnings=warnings,
        shard_metrics=shard_metrics,
        duplicate_report=duplicate_report,
        coverage={
            "coverage_claim": job.coverage_claim,
            "coverage_limitations": job.coverage_limitations,
            "closed_archived_coverage": job.closed_archived_coverage,
        },
    )


def evaluate_shard_completeness(
    shards: Sequence[HistoricalBackfillShard],
    *,
    thresholds: HistoricalQualityThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or HistoricalQualityThresholds()
    failures: list[str] = []
    status_counts: dict[str, int] = {}
    total_rows = 0
    accepted_count = 0
    blocking_count = 0
    unexplained_empty_count = 0
    over_cap_count = 0
    for shard in shards:
        status_counts[shard.status] = status_counts.get(shard.status, 0) + 1
        total_rows += int(shard.collected_rows or 0)
        if shard.status in ACCEPTED_STATUSES:
            accepted_count += 1
        if shard.status in BLOCKING_STATUSES:
            blocking_count += 1
            failures.append(f"{shard.shard_id}: blocking status {shard.status}: {shard.failure_reason or 'no reason'}")
        if shard.found is not None and shard.found >= thresholds.max_found_per_shard and shard.status != "split":
            over_cap_count += 1
            failures.append(f"{shard.shard_id}: found {shard.found} reaches result-depth cap")
        if shard.pages is not None and shard.pages >= thresholds.max_pages_per_shard and shard.status != "split":
            over_cap_count += 1
            failures.append(f"{shard.shard_id}: pages {shard.pages} reaches result-depth cap")
        if shard.status in ACCEPTED_STATUSES:
            if shard.found is None:
                failures.append(f"{shard.shard_id}: accepted shard has no found metadata")
            if shard.pages is None:
                failures.append(f"{shard.shard_id}: accepted shard has no page metadata")
            if not shard.status_code_summary:
                failures.append(f"{shard.shard_id}: accepted shard has no status_code_summary")
            if shard.status == "accepted" and shard.collected_rows <= 0:
                failures.append(f"{shard.shard_id}: accepted shard has no rows")
            if shard.status == "accepted" and not shard.output_keys:
                failures.append(f"{shard.shard_id}: accepted shard has no output_keys")
            if shard.status == "accepted" and not shard.checksum:
                failures.append(f"{shard.shard_id}: accepted shard has no checksum")
        if shard.collected_rows == 0 and not shard.expected_empty and shard.status != "split":
            unexplained_empty_count += 1
            if shard.status in ACCEPTED_STATUSES:
                failures.append(f"{shard.shard_id}: zero-row shard lacks expected_empty evidence")

    if not shards:
        failures.append("candidate has no shards")
    if accepted_count == 0:
        failures.append("candidate has no accepted shards")
    return {
        "status": "passed" if not failures else "failed",
        "shard_count": len(shards),
        "accepted_shards": accepted_count,
        "blocking_shards": blocking_count,
        "unexplained_empty_shards": unexplained_empty_count,
        "over_cap_shards": over_cap_count,
        "row_count": total_rows,
        "status_counts": status_counts,
        "failures": failures,
    }


def duplicate_conflict_report(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    total_rows = 0
    duplicates = 0
    conflicts: list[dict[str, Any]] = []
    first_seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        total_rows += 1
        key = canonical_vacancy_key(row)
        published_at = _string_or_none(row.get("published_at_iso") or row.get("published_at"))
        if key not in first_seen:
            first_seen[key] = {"published_at": published_at, "row": dict(row)}
            continue
        duplicates += 1
        previous = first_seen[key]
        if published_at and previous.get("published_at") and published_at != previous.get("published_at"):
            conflicts.append(
                {
                    "canonical_key": key,
                    "first_published_at": previous.get("published_at"),
                    "conflicting_published_at": published_at,
                }
            )
    duplicate_share = round(duplicates / total_rows, 6) if total_rows else 0.0
    return {
        "total_rows": total_rows,
        "unique_keys": len(first_seen),
        "duplicate_count": duplicates,
        "duplicate_share": duplicate_share,
        "conflict_count": len(conflicts),
        "conflicts": conflicts[:100],
    }


def canonical_vacancy_key(row: Mapping[str, Any]) -> str:
    source_id = _string_or_none(row.get("source_id") or row.get("source_mode") or "hh")
    source_vacancy_id = _string_or_none(
        row.get("source_vacancy_id") or row.get("hh_vacancy_id") or row.get("vacancy_id") or row.get("id")
    )
    if source_id and source_vacancy_id:
        return f"source:{source_id}:{source_vacancy_id}"
    url = _string_or_none(row.get("vacancy_url") or row.get("url") or row.get("hh_url"))
    if url:
        return "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    content = "|".join(
        _string_or_none(row.get(name)) or ""
        for name in ("title", "name", "company", "employer", "published_at_iso", "published_at")
    )
    return "content:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def thresholds_from_planning_config(config: HistoricalBackfillPlanningConfig) -> HistoricalQualityThresholds:
    return HistoricalQualityThresholds(
        max_found_per_shard=config.max_found_per_shard,
        max_pages_per_shard=config.max_pages_per_shard,
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
