"""Read-only dataset rollback readiness reporting."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

REPORT_VERSION = "skillra_rollback_readiness_report.v1"
DEFAULT_MIN_METADATA_COMPLETE_PUBLISHED_RUNS = 2
REQUIRED_ARTIFACT_TYPES = frozenset({"dataset_meta", "silver_features", "gold_market_view"})


def build_rollback_readiness_report(
    *,
    data_runs: Iterable[dict[str, Any]],
    active_status: dict[str, Any] | None,
    min_metadata_complete_published_runs: int = DEFAULT_MIN_METADATA_COMPLETE_PUBLISHED_RUNS,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    runs = list(data_runs)
    active = active_status.get("active") if isinstance(active_status, dict) else None
    active_run_id = str(active.get("run_id")) if isinstance(active, dict) and active.get("run_id") else None
    runs_by_id = {str(run.get("run_id")): run for run in runs if run.get("run_id")}
    active_run = _active_run(active, runs_by_id)

    published_runs = [run for run in runs if run.get("state") == "published"]
    complete_published_runs = [run for run in published_runs if _metadata_complete(run)["complete"]]
    rollback_candidates = [run for run in complete_published_runs if str(run.get("run_id")) != str(active_run_id or "")]
    active_completeness = _metadata_complete(active_run) if active_run else _missing_completeness("active_run_missing")
    complete_required = int(min_metadata_complete_published_runs)
    eligible = bool(
        active_run_id and active_completeness["complete"] and len(complete_published_runs) >= complete_required
    )

    blocked_reasons = _blocked_reasons(
        active_run_id=active_run_id,
        active_completeness=active_completeness,
        complete_published_runs=len(complete_published_runs),
        complete_required=complete_required,
        rollback_candidates=len(rollback_candidates),
    )
    return {
        "report_version": REPORT_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "status": "eligible" if eligible else "not_eligible",
        "active_run_id": active_run_id,
        "active_run_metadata_complete": active_completeness["complete"],
        "min_metadata_complete_published_runs": complete_required,
        "published_run_count": len(published_runs),
        "metadata_complete_published_run_count": len(complete_published_runs),
        "rollback_candidate_count": len(rollback_candidates),
        "blocked_reasons": blocked_reasons,
        "active_run": _run_summary(active_run, active_completeness),
        "rollback_candidates": [_run_summary(run, _metadata_complete(run)) for run in rollback_candidates],
        "metadata_complete_published_runs": [
            _run_summary(run, _metadata_complete(run)) for run in complete_published_runs
        ],
    }


def _active_run(active: object, runs_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(active, dict):
        return None
    embedded = active.get("run")
    if isinstance(embedded, dict):
        return embedded
    run_id = active.get("run_id")
    if run_id:
        return runs_by_id.get(str(run_id))
    return None


def _metadata_complete(run: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    if run.get("state") != "published":
        missing.append("state_published")
    if not run.get("dataset_meta_path"):
        missing.append("dataset_meta_path")
    if not run.get("manifest_uri"):
        missing.append("manifest_uri")
    if not run.get("quality_report_uri"):
        missing.append("quality_report_uri")
    if not _processed_rows_positive(run):
        missing.append("processed_rows_positive")

    artifact_types = _artifact_types_with_checksums(run)
    missing_artifacts = sorted(REQUIRED_ARTIFACT_TYPES - artifact_types)
    missing.extend(f"artifact:{artifact_type}" for artifact_type in missing_artifacts)

    processed_quality = run.get("processed_quality_report")
    if isinstance(processed_quality, dict) and processed_quality.get("status") != "passed":
        missing.append("processed_quality_passed")

    return {
        "complete": not missing,
        "missing": missing,
        "artifact_types_with_checksums": sorted(artifact_types),
    }


def _missing_completeness(reason: str) -> dict[str, Any]:
    return {"complete": False, "missing": [reason], "artifact_types_with_checksums": []}


def _processed_rows_positive(run: dict[str, Any]) -> bool:
    value = run.get("processed_rows")
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _artifact_types_with_checksums(run: dict[str, Any]) -> set[str]:
    artifact_uris = run.get("artifact_uris")
    artifacts = artifact_uris.get("artifacts") if isinstance(artifact_uris, dict) else None
    if not isinstance(artifacts, list):
        return set()
    result: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_type = artifact.get("type")
        sha = artifact.get("sha256")
        if artifact_type and sha:
            result.add(str(artifact_type))
    return result


def _blocked_reasons(
    *,
    active_run_id: str | None,
    active_completeness: dict[str, Any],
    complete_published_runs: int,
    complete_required: int,
    rollback_candidates: int,
) -> list[str]:
    reasons: list[str] = []
    if active_run_id is None:
        reasons.append("no_active_dataset_pointer")
    if not active_completeness["complete"]:
        reasons.append("active_run_is_not_metadata_complete")
    if complete_published_runs < complete_required:
        reasons.append("fewer_than_required_metadata_complete_published_runs")
    if rollback_candidates < 1:
        reasons.append("no_distinct_metadata_complete_rollback_candidate")
    return reasons


def _run_summary(run: dict[str, Any] | None, completeness: dict[str, Any]) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.get("run_id"),
        "state": run.get("state"),
        "source": run.get("source"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "processed_rows": run.get("processed_rows"),
        "dataset_meta_path": run.get("dataset_meta_path"),
        "manifest_uri": run.get("manifest_uri"),
        "quality_report_uri": run.get("quality_report_uri"),
        "metadata_complete": completeness["complete"],
        "missing": completeness["missing"],
        "artifact_types_with_checksums": completeness["artifact_types_with_checksums"],
    }
