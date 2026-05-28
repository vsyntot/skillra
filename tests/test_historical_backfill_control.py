from __future__ import annotations

from datetime import date
from pathlib import Path

from skillra_pda.ingest.historical_backfill_control import (
    HistoricalBackfillPlanningConfig,
    JsonBackfillStore,
    ShardObservation,
    SourceCircuitBreaker,
    TokenBucketRateLimiter,
    apply_shard_observations,
    block_job_for_source_capability,
    plan_historical_backfill,
)


def test_plan_historical_backfill_creates_day_area_shards() -> None:
    config = HistoricalBackfillPlanningConfig(
        backfill_id="test",
        source_mode="hh_api",
        requested_date_from=date(2025, 12, 1),
        requested_date_to=date(2025, 12, 2),
        areas=(113, 1),
    )

    job, shards = plan_historical_backfill(config)

    assert job.backfill_id == "test"
    assert job.shard_count == 4
    assert len(shards) == 4
    assert shards[0].date_from == "2025-12-01T00:00:00"
    assert shards[0].date_to == "2025-12-02T00:00:00"
    assert {shard.area_id for shard in shards} == {113, 1}


def test_over_cap_observation_splits_time_window() -> None:
    config = HistoricalBackfillPlanningConfig(
        backfill_id="test",
        source_mode="hh_api",
        requested_date_from=date(2025, 12, 1),
        requested_date_to=date(2025, 12, 1),
        areas=(113,),
        max_found_per_shard=100,
    )
    _job, shards = plan_historical_backfill(config)

    updated, summary = apply_shard_observations(
        shards,
        [ShardObservation(shard_id=shards[0].shard_id, found=100, pages=1, collected_rows=100)],
        config,
    )

    assert summary["split_parents"] == 1
    assert summary["new_child_shards"] == 2
    assert [shard.status for shard in updated].count("planned") == 2
    assert updated[0].status == "split"
    assert {child.parent_shard_id for child in updated[1:]} == {shards[0].shard_id}


def test_over_cap_min_window_splits_by_configured_dimension() -> None:
    config = HistoricalBackfillPlanningConfig(
        backfill_id="test",
        source_mode="hh_api",
        requested_date_from=date(2025, 12, 1),
        requested_date_to=date(2025, 12, 1),
        areas=(113,),
        split_experiences=("noExperience", "between1And3"),
        max_found_per_shard=100,
        min_time_window_minutes=1_440,
    )
    _job, shards = plan_historical_backfill(config)

    updated, summary = apply_shard_observations(
        shards,
        [ShardObservation(shard_id=shards[0].shard_id, found=100, pages=1, collected_rows=100)],
        config,
    )

    assert summary["new_child_shards"] == 2
    assert {shard.experience for shard in updated if shard.parent_shard_id == shards[0].shard_id} == {
        "noExperience",
        "between1And3",
    }


def test_json_backfill_store_roundtrips_snapshot(tmp_path: Path) -> None:
    config = HistoricalBackfillPlanningConfig(
        backfill_id="test",
        source_mode="hh_api",
        requested_date_from=date(2025, 12, 1),
        requested_date_to=date(2025, 12, 1),
        areas=(113,),
    )
    job, shards = plan_historical_backfill(config)
    store = JsonBackfillStore(tmp_path)

    with store.lock(job.backfill_id):
        summary = store.save_snapshot(job, shards)
    loaded_job, loaded_shards = store.load_snapshot("test")

    assert summary["shard_count"] == 1
    assert loaded_job.backfill_id == "test"
    assert loaded_shards[0].shard_id == shards[0].shard_id


def test_block_job_for_source_capability_marks_shards() -> None:
    config = HistoricalBackfillPlanningConfig(
        backfill_id="test",
        source_mode="hh_api",
        requested_date_from=date(2025, 12, 1),
        requested_date_to=date(2025, 12, 1),
        areas=(113,),
    )
    job, shards = plan_historical_backfill(config)

    job, shards = block_job_for_source_capability(job, shards, reason="HTTP 403")

    assert job.status == "blocked"
    assert shards[0].status == "blocked_source_capability"
    assert shards[0].failure_reason == "HTTP 403"


def test_runtime_policy_helpers_are_deterministic() -> None:
    limiter = TokenBucketRateLimiter(rate_per_second=2, capacity=1)
    assert limiter.reserve(now=10.0) == 0.0
    assert limiter.reserve(now=10.0) == 0.5

    breaker = SourceCircuitBreaker(failure_threshold=2, reset_seconds=10)
    breaker.record_failure(now=1.0)
    assert breaker.is_open(now=1.0) is False
    breaker.record_failure(now=2.0)
    assert breaker.is_open(now=3.0) is True
    assert breaker.is_open(now=13.0) is False
