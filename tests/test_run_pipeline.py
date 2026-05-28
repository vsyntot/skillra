"""Tests for pipeline orchestration helpers."""

from pathlib import Path

import pandas as pd
import pytest

from scripts.run_pipeline import (
    _build_run_manifest,
    _data_scope_summary,
    _evaluate_quality_gates,
    _evaluate_trend_ready_gate,
    _lineage_metadata,
    _market_trust_summary,
    _observed_publication_range,
    _product_eligibility,
    _publish_latest_if_quality_passed,
    _resolve_run_id,
    _segment_quality_report,
    _update_latest_dir,
)
from skillra_pda.ingest.source_registry import build_source_capability_ref


def test_update_latest_dir_uses_portable_relative_symlink(tmp_path: Path) -> None:
    processed_dir = tmp_path / "data" / "processed"
    run_dir = processed_dir / "runs" / "20260519T120000Z"
    latest_dir = processed_dir / "latest"
    run_dir.mkdir(parents=True)
    artifact = run_dir / "dataset_meta.json"
    artifact.write_text("{}", encoding="utf-8")

    _update_latest_dir(latest_dir, run_dir, (artifact,))

    if latest_dir.is_symlink():
        assert latest_dir.readlink() == Path("runs") / "20260519T120000Z"
    else:
        assert (latest_dir / "dataset_meta.json").read_text(encoding="utf-8") == "{}"


def test_resolve_run_id_uses_explicit_pipeline_runner_id() -> None:
    assert (
        _resolve_run_id("20260519T160609Z", pd.Timestamp("2026-05-19T16:06:16Z").to_pydatetime()) == "20260519T160609Z"
    )


def test_resolve_run_id_rejects_path_like_values() -> None:
    with pytest.raises(ValueError, match="run id"):
        _resolve_run_id("../bad", pd.Timestamp("2026-05-19T16:06:16Z").to_pydatetime())


def test_evaluate_quality_gates_passes_valid_dataset() -> None:
    features = pd.DataFrame(
        {
            "vacancy_id": ["1", "2", "3"],
            "title": ["Data Analyst", "ML Engineer", "Backend Developer"],
            "primary_role": ["analyst", "ml", "backend"],
            "grade_final": ["junior", "middle", "senior"],
            "city_tier": ["Moscow", "SPb", "Other RU"],
            "work_mode": ["remote", "hybrid", "office"],
            "salary_mid": [100000, 200000, None],
        }
    )
    market_view = pd.DataFrame({"primary_role": ["analyst"], "vacancy_count": [3]})

    quality = _evaluate_quality_gates(
        features,
        market_view,
        thresholds={"min_rows": 3, "min_salary_known_share": 0.5, "min_market_view_rows": 1},
    )

    assert quality["status"] == "passed"
    assert quality["failed_gates"] == []
    assert quality["metrics"]["salary_known_share"] == 0.666667
    assert quality["metrics"]["unknown_geo_share"] == 0.0
    assert quality["metrics"]["unknown_work_mode_share"] == 0.0


def test_segment_quality_and_product_eligibility_surface_low_confidence_segments() -> None:
    features = pd.DataFrame(
        {
            "vacancy_id": ["1", "2", "3"],
            "title": ["A", "B", "C"],
            "primary_role": ["analyst", "unknown", "backend"],
            "grade_final": ["junior", "junior", "middle"],
            "city_tier": ["Moscow", "Moscow", "SPb"],
            "work_mode": ["remote", "remote", "office"],
            "salary_mid": [100000, None, None],
        }
    )
    market_view = pd.DataFrame({"primary_role": ["analyst"], "vacancy_count": [3]})
    quality = _evaluate_quality_gates(features, market_view, thresholds={"min_rows": 3, "min_market_view_rows": 1})
    segment_report = _segment_quality_report(features, thresholds={"min_segment_rows": 2})
    eligibility = _product_eligibility(
        quality,
        segment_report,
        {"dataset_semantic_type": "current_market_snapshot", "date_semantics_status": None},
    )

    assert segment_report["status"] == "warning"
    assert segment_report["low_confidence_segment_count"] > 0
    assert eligibility["search"]["eligible"] is True
    assert eligibility["trends"]["eligible"] is False


def test_trend_ready_gate_requires_source_capability_and_period_coverage() -> None:
    features = pd.DataFrame(
        {
            "vacancy_id": [str(index) for index in range(1, 9)],
            "title": [f"Vacancy {index}" for index in range(1, 9)],
            "primary_role": ["analyst"] * 8,
            "grade_final": ["middle"] * 8,
            "city_tier": ["Moscow"] * 8,
            "work_mode": ["remote"] * 8,
            "salary_mid": [100000 + index for index in range(8)],
            "published_at_iso": [f"2025-{month:02d}-01" for month in range(1, 9)],
        }
    )
    market_view = pd.DataFrame({"primary_role": ["analyst"], "vacancy_count": [8]})
    quality = _evaluate_quality_gates(
        features,
        market_view,
        thresholds={"min_rows": 8, "min_salary_known_share": 1.0, "min_market_view_rows": 1},
    )
    segment_report = _segment_quality_report(
        features,
        thresholds={"min_segment_rows": 1, "min_segment_salary_known_share": 0.0},
    )
    lineage = {
        "dataset_semantic_type": "historical_publication_facts",
        "date_semantics_status": "passed",
        "source_capability_ref": build_source_capability_ref(
            source_mode="fixture",
            use_case="historical_collection",
            capability_status="supported",
            evidence_type="test_fixture",
            dataset_scope="all_vacancies",
            salary_only=False,
        ),
    }

    gate = _evaluate_trend_ready_gate(
        features,
        quality,
        segment_report,
        lineage,
        thresholds={"trend_min_complete_periods": 8, "trend_min_salary_known_share": 1.0},
    )
    eligibility = _product_eligibility(quality, segment_report, lineage, gate)

    assert gate["eligible"] is True
    assert eligibility["trends"]["eligible"] is True


def test_trend_ready_gate_blocks_without_source_capability() -> None:
    features = pd.DataFrame(
        {
            "vacancy_id": ["1", "2"],
            "title": ["A", "B"],
            "primary_role": ["analyst", "analyst"],
            "grade_final": ["middle", "middle"],
            "city_tier": ["Moscow", "Moscow"],
            "work_mode": ["remote", "remote"],
            "salary_mid": [100000, 110000],
            "published_at_iso": ["2025-01-01", "2025-02-01"],
        }
    )
    market_view = pd.DataFrame({"primary_role": ["analyst"], "vacancy_count": [2]})
    quality = _evaluate_quality_gates(features, market_view, thresholds={"min_rows": 2, "min_market_view_rows": 1})
    segment_report = _segment_quality_report(features, thresholds={"min_segment_rows": 1})
    gate = _evaluate_trend_ready_gate(
        features,
        quality,
        segment_report,
        {"dataset_semantic_type": "historical_publication_facts", "date_semantics_status": "passed"},
        thresholds={"trend_min_complete_periods": 2},
    )

    assert gate["eligible"] is False
    assert "source_capability_supported" in gate["failed_criteria"]


def test_market_trust_summary_uses_salary_coverage_fields() -> None:
    market_view = pd.DataFrame(
        {
            "vacancy_count": [10, 20],
            "salary_sample_size": [4, 10],
            "confidence": ["low", "medium"],
        }
    )

    summary = _market_trust_summary(market_view)

    assert summary == {
        "vacancy_count": 30,
        "salary_sample_size": 14,
        "salary_coverage_share": 0.466667,
        "confidence_counts": {"low": 1, "medium": 1},
    }


def test_data_scope_summary_uses_dataset_scope_and_salary_disclosed() -> None:
    features = pd.DataFrame(
        {
            "dataset_scope": ["all_vacancies", "all_vacancies", "salary_disclosed"],
            "salary_disclosed": [False, True, True],
        }
    )

    summary = _data_scope_summary(features)

    assert summary == {
        "row_count": 3,
        "dataset_scope_counts": {"all_vacancies": 2, "salary_disclosed": 1},
        "salary_disclosed_count": 2,
        "salary_disclosure_share": 0.666667,
    }


def test_lineage_metadata_distinguishes_historical_facts_from_current_snapshot() -> None:
    features = pd.DataFrame(
        {
            "published_at_iso": ["2025-12-01", "2025-12-02T12:00:00+03:00"],
        }
    )
    ingestion = {
        "source_mode": "minio_backfill_completed",
        "requested_date_from": "2025-12-01",
        "requested_date_to": "2025-12-02",
        "date_semantics": {"status": "passed"},
    }

    lineage = _lineage_metadata(features, ingestion)

    assert _observed_publication_range(features) == {
        "observed_published_at_from": "2025-12-01",
        "observed_published_at_to": "2025-12-02",
    }
    assert lineage["source_kind"] == "minio_backfill_completed"
    assert lineage["dataset_semantic_type"] == "historical_publication_facts"
    assert lineage["date_semantics_status"] == "passed"


def test_evaluate_quality_gates_fails_bad_dataset() -> None:
    features = pd.DataFrame(
        {
            "vacancy_id": ["1", "1"],
            "title": ["Unknown", "Unknown"],
            "primary_role": ["other", "other"],
            "grade_final": ["unknown", "unknown"],
            "city_tier": ["unknown", "unknown"],
            "work_mode": ["unknown", "unknown"],
        }
    )
    market_view = pd.DataFrame()

    quality = _evaluate_quality_gates(features, market_view, thresholds={"min_rows": 3})

    assert quality["status"] == "failed"
    assert set(quality["failed_gates"]) >= {
        "min_rows",
        "duplicate_share",
        "salary_known_share",
        "unknown_role_share",
        "unknown_grade_share",
        "min_market_view_rows",
    }


def test_evaluate_quality_gates_handles_categorical_missing_values() -> None:
    features = pd.DataFrame(
        {
            "vacancy_id": ["1", "2", "3"],
            "title": ["Data Analyst", "ML Engineer", "Backend Developer"],
            "primary_role": pd.Categorical(["analyst", None, "backend"], categories=["analyst", "backend"]),
            "grade_final": pd.Categorical(["junior", "middle", None], categories=["junior", "middle"]),
            "city_tier": ["Moscow", "SPb", "Other RU"],
            "work_mode": ["remote", "hybrid", "office"],
            "salary_mid": [100000, 200000, None],
        }
    )
    market_view = pd.DataFrame({"primary_role": ["analyst"], "vacancy_count": [3]})

    quality = _evaluate_quality_gates(
        features,
        market_view,
        thresholds={"min_rows": 3, "min_salary_known_share": 0.5, "min_market_view_rows": 1},
    )

    assert quality["status"] == "passed"


def test_publish_latest_if_quality_failed_leaves_existing_latest_untouched(tmp_path: Path) -> None:
    processed_dir = tmp_path / "data" / "processed"
    old_run = processed_dir / "runs" / "old"
    failed_run = processed_dir / "runs" / "failed"
    latest_dir = processed_dir / "latest"
    old_run.mkdir(parents=True)
    failed_run.mkdir(parents=True)
    old_artifact = old_run / "dataset_meta.json"
    new_artifact = failed_run / "dataset_meta.json"
    old_artifact.write_text('{"run_id":"old"}', encoding="utf-8")
    new_artifact.write_text('{"run_id":"failed"}', encoding="utf-8")
    _update_latest_dir(latest_dir, old_run, (old_artifact,))

    with pytest.raises(RuntimeError, match="Data quality gates failed"):
        _publish_latest_if_quality_passed(
            latest_dir,
            failed_run,
            (new_artifact,),
            {"status": "failed", "failed_gates": ["min_rows"]},
        )

    if latest_dir.is_symlink():
        assert latest_dir.readlink() == Path("runs") / "old"
    else:
        assert (latest_dir / "dataset_meta.json").read_text(encoding="utf-8") == '{"run_id":"old"}'


def test_build_run_manifest_includes_checksums_and_lake_keys(tmp_path: Path) -> None:
    run_id = "20260519T120000Z"
    artifacts = []
    artifact_names = [
        "hh_clean.parquet",
        "hh_features.parquet",
        "market_view.parquet",
        "dataset_meta.json",
        "quality_report.json",
    ]
    for name in artifact_names:
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        artifacts.append(path)

    manifest = _build_run_manifest(
        run_id=run_id,
        run_timestamp=pd.Timestamp("2026-05-19T12:00:00Z").to_pydatetime(),
        dataset_meta={
            "source_kind": "fixture",
            "dataset_semantic_type": "current_market_snapshot",
            "features_rows": 3,
            "market_view_rows": 1,
            "processed_quality_report": {"status": "passed"},
            "quality_gates": {"failed_gates": []},
            "product_eligibility": {"search": {"eligible": True}},
        },
        artifacts=tuple(artifacts),
        ingestion_payload={"last_run_id": "raw-run", "schema_version": "1"},
    )

    assert manifest["manifest_schema_version"] == "2"
    assert manifest["run_id"] == run_id
    assert manifest["raw_run_id"] == "raw-run"
    assert manifest["source_lineage"]["dataset_semantic_type"] == "current_market_snapshot"
    assert manifest["quality_decision"]["processed_status"] == "passed"
    assert manifest["quality_decision"]["product_eligibility"]["search"]["eligible"] is True
    assert manifest["publish_decision"]["latest_eligible"] is True
    assert manifest["serving_consumers"]["api_datastore"]["status"] == "planned_after_reload"
    assert {artifact["type"] for artifact in manifest["artifacts"]} >= {"silver_features", "quality_report"}
    assert f"hh/silver/run={run_id}/hh_features.parquet" in {artifact["lake_key"] for artifact in manifest["artifacts"]}
    assert all(artifact["sha256"] for artifact in manifest["artifacts"])
