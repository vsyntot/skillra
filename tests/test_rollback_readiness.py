from __future__ import annotations

from datetime import datetime, timezone

from skillra_pda.rollback_readiness import build_rollback_readiness_report


def _run(run_id: str, *, state: str = "published", complete: bool = True) -> dict:
    payload = {
        "run_id": run_id,
        "state": state,
        "source": "pipeline",
        "started_at": "2026-05-27T00:00:00+00:00",
        "finished_at": "2026-05-27T00:10:00+00:00",
        "processed_rows": 100,
        "dataset_meta_path": f"data/processed/runs/{run_id}/dataset_meta.json",
        "manifest_uri": f"s3://processed/hh/manifests/run={run_id}/manifest.json",
        "quality_report_uri": f"s3://processed/hh/manifests/run={run_id}/quality_report.json",
        "artifact_uris": {
            "artifacts": [
                {"type": "dataset_meta", "sha256": "a"},
                {"type": "silver_features", "sha256": "b"},
                {"type": "gold_market_view", "sha256": "c"},
            ]
        },
        "processed_quality_report": {"status": "passed"},
    }
    if not complete:
        payload["artifact_uris"] = {"artifacts": [{"type": "dataset_meta", "sha256": "a"}]}
    return payload


def _active(run: dict) -> dict:
    return {"state": run["state"], "active": {"run_id": run["run_id"], "run": run}}


def test_report_is_not_eligible_with_single_complete_published_run() -> None:
    current = _run("run-current")

    report = build_rollback_readiness_report(
        data_runs=[current],
        active_status=_active(current),
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert report["status"] == "not_eligible"
    assert report["active_run_metadata_complete"] is True
    assert report["metadata_complete_published_run_count"] == 1
    assert report["rollback_candidate_count"] == 0
    assert "no_distinct_metadata_complete_rollback_candidate" in report["blocked_reasons"]


def test_report_is_eligible_with_distinct_complete_published_candidate() -> None:
    previous = _run("run-previous")
    current = _run("run-current")

    report = build_rollback_readiness_report(
        data_runs=[current, previous],
        active_status=_active(current),
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert report["status"] == "eligible"
    assert report["active_run_id"] == "run-current"
    assert report["metadata_complete_published_run_count"] == 2
    assert report["rollback_candidate_count"] == 1
    assert report["rollback_candidates"][0]["run_id"] == "run-previous"
    assert report["blocked_reasons"] == []


def test_report_blocks_when_active_run_lacks_required_artifact_checksums() -> None:
    previous = _run("run-previous")
    current = _run("run-current", complete=False)

    report = build_rollback_readiness_report(
        data_runs=[current, previous],
        active_status=_active(current),
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert report["status"] == "not_eligible"
    assert report["active_run_metadata_complete"] is False
    assert "active_run_is_not_metadata_complete" in report["blocked_reasons"]
    assert "artifact:gold_market_view" in report["active_run"]["missing"]
    assert "artifact:silver_features" in report["active_run"]["missing"]


def test_report_uses_active_run_from_history_when_active_payload_has_no_embedded_run() -> None:
    current = _run("run-current")
    active_status = {"state": "published", "active": {"run_id": "run-current"}}

    report = build_rollback_readiness_report(
        data_runs=[current],
        active_status=active_status,
        generated_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )

    assert report["active_run"]["run_id"] == "run-current"
    assert report["active_run_metadata_complete"] is True
