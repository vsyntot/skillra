from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from skillra_pda.trend_readiness import (
    build_trend_readiness_report,
    evidence_from_meta,
    load_processed_run_evidence,
)


def _meta(
    run_id: str,
    generated_at_utc: str,
    *,
    semantic_type: str = "current_market_snapshot",
    quality_status: str = "passed",
    date_semantics_status: str | None = None,
    trend_eligible: bool = False,
) -> dict:
    return {
        "run_id": run_id,
        "generated_at_utc": generated_at_utc,
        "dataset_semantic_type": semantic_type,
        "source_kind": "hh_daily_refresh",
        "date_semantics_status": date_semantics_status,
        "processed_quality_report": {"status": quality_status},
        "observed_published_at_from": "2026-05-01",
        "observed_published_at_to": "2026-05-02",
        "trend_ready_gate": {
            "eligible": trend_eligible,
            "status": "passed" if trend_eligible else "blocked",
            "failed_criteria": [] if trend_eligible else ["historical_publication_facts"],
        },
    }


def _write_meta(processed_runs_dir: Path, payload: dict) -> None:
    run_dir = processed_runs_dir / payload["run_id"]
    run_dir.mkdir(parents=True)
    (run_dir / "dataset_meta.json").write_text(json.dumps(payload), encoding="utf-8")


def test_load_processed_run_evidence_reads_dataset_meta(tmp_path: Path) -> None:
    runs_dir = tmp_path / "processed" / "runs"
    _write_meta(runs_dir, _meta("run-1", "2026-05-04T12:00:00+00:00"))

    evidence = load_processed_run_evidence(runs_dir)

    assert len(evidence) == 1
    assert evidence[0].run_id == "run-1"
    assert evidence[0].generated_week == "2026-W19"
    assert evidence[0].is_quality_passed_current_snapshot is True


def test_report_blocks_without_processed_runs() -> None:
    report = build_trend_readiness_report([], generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc))

    assert report["status"] == "blocked_no_evidence"
    assert report["public_trends_allowed"] is False
    assert "no_processed_dataset_runs" in report["blocked_reasons"]


def test_report_counts_forward_current_snapshot_weeks() -> None:
    evidence = [
        evidence_from_meta(_meta("run-1", "2026-05-04T12:00:00+00:00")),
        evidence_from_meta(_meta("run-2", "2026-05-11T12:00:00+00:00")),
        evidence_from_meta(_meta("run-3", "2026-05-18T12:00:00+00:00")),
        evidence_from_meta(_meta("run-4", "2026-05-27T12:00:00+00:00")),
    ]

    report = build_trend_readiness_report(
        evidence,
        min_forward_weeks=8,
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert report["status"] == "forward_accumulating"
    assert report["forward_build"]["complete_weeks_observed"] == 3
    assert report["forward_build"]["generated_weeks_observed"] == 4
    assert report["forward_build"]["complete_weeks"] == ["2026-W19", "2026-W20", "2026-W21"]
    assert report["forward_build"]["current_partial_week"] == "2026-W22"
    assert report["forward_build"]["source_kind_counts"] == {"hh_daily_refresh": 4}
    assert report["forward_build"]["weeks_remaining"] == 5
    assert report["claim_status"] == "blocked"


def test_report_tracks_current_partial_week_as_forward_accumulating() -> None:
    evidence = [evidence_from_meta(_meta("run-current", "2026-05-27T12:00:00+00:00"))]

    report = build_trend_readiness_report(
        evidence,
        min_forward_weeks=8,
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert report["status"] == "forward_accumulating"
    assert report["forward_build"]["complete_weeks_observed"] == 0
    assert report["forward_build"]["current_partial_week"] == "2026-W22"
    assert report["public_trends_allowed"] is False


def test_report_marks_forward_window_ready_for_review_without_unlocking_public_claims() -> None:
    evidence = [
        evidence_from_meta(_meta(f"run-{index}", f"2026-{month:02d}-01T12:00:00+00:00"))
        for index, month in enumerate(range(1, 9), start=1)
    ]

    report = build_trend_readiness_report(
        evidence,
        min_forward_weeks=8,
        generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert report["status"] == "forward_window_ready_for_review"
    assert report["forward_build"]["complete_weeks_observed"] == 8
    assert report["public_trends_allowed"] is False
    assert (
        "forward_history_needs_explicit_product_and_data_model_review_before_claim_unlock" in report["blocked_reasons"]
    )


def test_report_allows_only_latest_historical_trend_ready_dataset() -> None:
    current = evidence_from_meta(_meta("run-current", "2026-05-18T12:00:00+00:00"))
    historical = evidence_from_meta(
        _meta(
            "run-historical",
            "2026-05-27T12:00:00+00:00",
            semantic_type="historical_publication_facts",
            date_semantics_status="passed",
            trend_eligible=True,
        )
    )

    report = build_trend_readiness_report([current, historical], min_forward_weeks=8)

    assert report["status"] == "historical_trend_ready"
    assert report["public_trends_allowed"] is True
    assert report["claim_status"] == "ready"
    assert report["historical_gate"]["ready_run_count"] == 1


def test_report_keeps_public_blocked_when_historical_candidate_is_not_latest() -> None:
    historical = evidence_from_meta(
        _meta(
            "run-historical",
            "2026-05-18T12:00:00+00:00",
            semantic_type="historical_publication_facts",
            date_semantics_status="passed",
            trend_eligible=True,
        )
    )
    current = evidence_from_meta(_meta("run-current", "2026-05-27T12:00:00+00:00"))

    report = build_trend_readiness_report(
        [historical, current],
        min_forward_weeks=8,
        generated_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    assert report["status"] == "forward_accumulating"
    assert report["public_trends_allowed"] is False
    assert report["historical_gate"]["ready_run_count"] == 1
