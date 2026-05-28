from __future__ import annotations

from datetime import date

from skillra_pda.ingest.historical_backfill_control import (
    HistoricalBackfillPlanningConfig,
    ShardObservation,
    apply_shard_observations,
    plan_historical_backfill,
)
from skillra_pda.ingest.historical_quality import (
    duplicate_conflict_report,
    evaluate_historical_candidate,
)
from skillra_pda.ingest.source_registry import build_source_capability_ref


def _accepted_job_and_shards():
    source_ref = build_source_capability_ref(
        source_mode="fixture",
        use_case="historical_collection",
        capability_status="supported",
        evidence_type="test_fixture",
        requested_date_from="2025-12-01",
        requested_date_to="2025-12-01",
        dataset_scope="all_vacancies",
        salary_only=False,
        areas=[113],
        coverage_claim="retrievable_through_proven_source",
        coverage_limitations=["fixture"],
        closed_archived_coverage="test_fixture",
    )
    config = HistoricalBackfillPlanningConfig(
        backfill_id="test",
        source_mode="fixture",
        requested_date_from=date(2025, 12, 1),
        requested_date_to=date(2025, 12, 1),
        areas=(113,),
        source_capability_ref=source_ref,
        coverage_claim="retrievable_through_proven_source",
        coverage_limitations=("fixture",),
        closed_archived_coverage="test_fixture",
    )
    job, shards = plan_historical_backfill(config)
    shards, _summary = apply_shard_observations(
        shards,
        [
            ShardObservation(
                shard_id=shards[0].shard_id,
                found=1,
                pages=1,
                collected_rows=1,
                status_code_summary={"200": 1},
                output_keys=("backfills/test/normalized/shard.csv",),
                checksum="abc",
            )
        ],
        config,
    )
    return job, shards


def test_historical_candidate_accepts_complete_fixture_state() -> None:
    job, shards = _accepted_job_and_shards()

    result = evaluate_historical_candidate(job, shards)

    assert result.status == "accepted"
    assert result.failures == []
    assert result.shard_metrics["accepted_shards"] == 1


def test_historical_candidate_blocks_unsupported_source() -> None:
    job, shards = _accepted_job_and_shards()
    job.source_capability_ref = None

    result = evaluate_historical_candidate(job, shards)

    assert result.status == "blocked"
    assert any("source_capability_ref must be an object" in failure for failure in result.failures)


def test_historical_candidate_blocks_shard_without_output_evidence() -> None:
    job, shards = _accepted_job_and_shards()
    shards[0].output_keys = []

    result = evaluate_historical_candidate(job, shards)

    assert result.status == "blocked"
    assert any("accepted shard has no output_keys" in failure for failure in result.failures)


def test_duplicate_conflict_report_detects_publication_conflicts() -> None:
    report = duplicate_conflict_report(
        [
            {"source_id": "hh", "source_vacancy_id": "1", "published_at_iso": "2025-12-01"},
            {"source_id": "hh", "source_vacancy_id": "1", "published_at_iso": "2025-12-02"},
            {"source_id": "hh", "source_vacancy_id": "2", "published_at_iso": "2025-12-02"},
        ]
    )

    assert report["duplicate_count"] == 1
    assert report["conflict_count"] == 1
    assert report["duplicate_share"] == 0.333333
