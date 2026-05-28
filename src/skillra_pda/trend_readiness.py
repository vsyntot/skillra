"""Forward-built trend readiness reporting helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPORT_VERSION = "skillra_trend_readiness_report.v1"
DEFAULT_MIN_FORWARD_WEEKS = 8


@dataclass(frozen=True)
class DatasetRunTrendEvidence:
    run_id: str
    generated_at_utc: datetime | None
    generated_week: str | None
    dataset_semantic_type: str | None
    source_kind: str | None
    quality_status: str | None
    date_semantics_status: str | None
    observed_published_at_from: str | None
    observed_published_at_to: str | None
    trend_gate_eligible: bool
    trend_gate_status: str | None
    trend_failed_criteria: tuple[str, ...]

    @property
    def is_quality_passed_current_snapshot(self) -> bool:
        return self.quality_status == "passed" and self.dataset_semantic_type == "current_market_snapshot"

    @property
    def is_public_trend_ready_historical(self) -> bool:
        return (
            self.quality_status == "passed"
            and self.dataset_semantic_type == "historical_publication_facts"
            and self.date_semantics_status == "passed"
            and self.trend_gate_eligible
        )


def load_dataset_meta(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_processed_run_evidence(processed_runs_dir: Path) -> list[DatasetRunTrendEvidence]:
    if not processed_runs_dir.exists():
        return []
    evidence: list[DatasetRunTrendEvidence] = []
    for meta_path in sorted(processed_runs_dir.glob("*/dataset_meta.json")):
        evidence.append(evidence_from_meta(load_dataset_meta(meta_path), fallback_run_id=meta_path.parent.name))
    return evidence


def evidence_from_meta(meta: dict[str, Any], *, fallback_run_id: str | None = None) -> DatasetRunTrendEvidence:
    generated_at = _parse_datetime(_first_present(meta, "generated_at_utc", "generated_at", "created_at"))
    quality_report = meta.get("processed_quality_report")
    quality_status = None
    if isinstance(quality_report, dict):
        quality_status = _string_or_none(quality_report.get("status"))
    quality_gates = meta.get("quality_gates")
    if quality_status is None and isinstance(quality_gates, dict):
        quality_status = _string_or_none(quality_gates.get("status"))

    trend_gate = meta.get("trend_ready_gate")
    trend_gate_dict = trend_gate if isinstance(trend_gate, dict) else {}
    failed_criteria = trend_gate_dict.get("failed_criteria")
    return DatasetRunTrendEvidence(
        run_id=str(meta.get("run_id") or fallback_run_id or "unknown"),
        generated_at_utc=generated_at,
        generated_week=_iso_week(generated_at.date()) if generated_at else None,
        dataset_semantic_type=_string_or_none(meta.get("dataset_semantic_type")),
        source_kind=_string_or_none(meta.get("source_kind")),
        quality_status=quality_status,
        date_semantics_status=_string_or_none(meta.get("date_semantics_status")),
        observed_published_at_from=_string_or_none(meta.get("observed_published_at_from")),
        observed_published_at_to=_string_or_none(meta.get("observed_published_at_to")),
        trend_gate_eligible=trend_gate_dict.get("eligible") is True,
        trend_gate_status=_string_or_none(trend_gate_dict.get("status")),
        trend_failed_criteria=tuple(str(item) for item in failed_criteria) if isinstance(failed_criteria, list) else (),
    )


def build_trend_readiness_report(
    evidence: Iterable[DatasetRunTrendEvidence],
    *,
    min_forward_weeks: int = DEFAULT_MIN_FORWARD_WEEKS,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    sorted_runs = sorted(
        list(evidence),
        key=lambda item: item.generated_at_utc or datetime.min.replace(tzinfo=timezone.utc),
    )
    quality_current_runs = [item for item in sorted_runs if item.is_quality_passed_current_snapshot]
    observed_forward_weeks = sorted({item.generated_week for item in quality_current_runs if item.generated_week})
    current_week = _iso_week(generated_at.date())
    complete_forward_weeks = [week for week in observed_forward_weeks if week < current_week]
    historical_ready_runs = [item for item in sorted_runs if item.is_public_trend_ready_historical]
    latest_run = sorted_runs[-1] if sorted_runs else None
    latest_ready = bool(latest_run and latest_run.is_public_trend_ready_historical)

    weeks_observed = len(complete_forward_weeks)
    weeks_remaining = max(0, int(min_forward_weeks) - weeks_observed)
    if latest_ready:
        status = "historical_trend_ready"
        public_trends_allowed = True
    elif weeks_observed >= int(min_forward_weeks):
        status = "forward_window_ready_for_review"
        public_trends_allowed = False
    elif observed_forward_weeks:
        status = "forward_accumulating"
        public_trends_allowed = False
    else:
        status = "blocked_no_evidence"
        public_trends_allowed = False

    blocked_reasons = _blocked_reasons(
        status=status,
        public_trends_allowed=public_trends_allowed,
        weeks_remaining=weeks_remaining,
        latest_run=latest_run,
    )
    return {
        "report_version": REPORT_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "status": status,
        "claim_status": "ready" if public_trends_allowed else "blocked",
        "public_trends_allowed": public_trends_allowed,
        "min_forward_weeks": int(min_forward_weeks),
        "forward_build": {
            "quality_current_snapshot_runs": len(quality_current_runs),
            "source_kind_counts": _counts_by(item.source_kind or "unknown" for item in quality_current_runs),
            "complete_weeks_observed": weeks_observed,
            "generated_weeks_observed": len(observed_forward_weeks),
            "weeks_remaining": weeks_remaining,
            "first_complete_week": complete_forward_weeks[0] if complete_forward_weeks else None,
            "latest_complete_week": complete_forward_weeks[-1] if complete_forward_weeks else None,
            "current_partial_week": current_week if current_week in observed_forward_weeks else None,
            "complete_weeks": complete_forward_weeks,
            "observed_weeks": observed_forward_weeks,
        },
        "historical_gate": {
            "ready_run_count": len(historical_ready_runs),
            "latest_run_is_public_trend_ready": latest_ready,
            "ready_runs": [_run_summary(item) for item in historical_ready_runs],
        },
        "latest_run": _run_summary(latest_run) if latest_run else None,
        "blocked_reasons": blocked_reasons,
        "next_actions": _next_actions(status, weeks_remaining),
    }


def _blocked_reasons(
    *,
    status: str,
    public_trends_allowed: bool,
    weeks_remaining: int,
    latest_run: DatasetRunTrendEvidence | None,
) -> list[str]:
    if public_trends_allowed:
        return []
    reasons: list[str] = []
    if latest_run is None:
        reasons.append("no_processed_dataset_runs")
    elif not latest_run.is_public_trend_ready_historical:
        reasons.append("latest_dataset_is_not_public_trend_ready_historical_facts")
        if latest_run.dataset_semantic_type != "historical_publication_facts":
            reasons.append("latest_dataset_semantic_type_is_not_historical_publication_facts")
        if latest_run.date_semantics_status != "passed":
            reasons.append("latest_date_semantics_not_passed")
        if not latest_run.trend_gate_eligible:
            reasons.append("latest_trend_ready_gate_not_eligible")
    if status == "forward_accumulating" and weeks_remaining > 0:
        reasons.append("forward_current_snapshot_history_has_too_few_complete_weeks")
    if status == "forward_window_ready_for_review":
        reasons.append("forward_history_needs_explicit_product_and_data_model_review_before_claim_unlock")
    return reasons


def _next_actions(status: str, weeks_remaining: int) -> list[str]:
    if status == "historical_trend_ready":
        return ["verify trend endpoints and release claim copy before public exposure"]
    if status == "forward_window_ready_for_review":
        return [
            "review forward-built snapshot semantics against product trend claims",
            "decide whether accumulated current snapshots can power period-over-period claims",
            "add an ADR before changing public trend eligibility",
        ]
    if status == "forward_accumulating":
        return [
            f"continue daily controlled current snapshots until at least {weeks_remaining} more complete weeks exist",
            "keep public trend endpoints blocked",
        ]
    return [
        "produce controlled processed dataset runs before evaluating trend readiness",
        "keep public trend endpoints blocked",
    ]


def _counts_by(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _run_summary(item: DatasetRunTrendEvidence | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "run_id": item.run_id,
        "generated_at_utc": item.generated_at_utc.isoformat() if item.generated_at_utc else None,
        "generated_week": item.generated_week,
        "dataset_semantic_type": item.dataset_semantic_type,
        "source_kind": item.source_kind,
        "quality_status": item.quality_status,
        "date_semantics_status": item.date_semantics_status,
        "observed_published_at_from": item.observed_published_at_from,
        "observed_published_at_to": item.observed_published_at_to,
        "trend_gate_eligible": item.trend_gate_eligible,
        "trend_gate_status": item.trend_gate_status,
        "trend_failed_criteria": list(item.trend_failed_criteria),
    }


def _first_present(mapping: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return None


def _string_or_none(value: Any | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_datetime(value: Any | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"
