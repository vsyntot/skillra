from __future__ import annotations

"""Run the end-to-end data cleaning and feature engineering pipeline."""
import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.skillra_pda import cleaning, config, features, io, market, timeseries  # noqa: E402
from src.skillra_pda.ingest.date_semantics import parse_date_value  # noqa: E402
from src.skillra_pda.ingest.source_registry import (  # noqa: E402
    TREND_BLOCKED_USER_MESSAGE,
    TREND_READY_GATE_VERSION,
    validate_source_capability_ref,
)

logger = logging.getLogger(__name__)

UNKNOWN_VALUES = {"", "unknown", "other", "none", "nan", "n/a"}
REQUIRED_FEATURE_COLUMNS = ("title", "primary_role", "grade_final", "city_tier", "work_mode")
ID_COLUMNS = ("hh_vacancy_id", "vacancy_id", "id")
SEGMENT_GATE_COLUMNS = ("primary_role", "grade_final", "city_tier", "work_mode", "domain")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer env %s=%r, using default %s", name, raw, default)
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float env %s=%r, using default %s", name, raw, default)
        return default


def _quality_thresholds() -> dict[str, float | int]:
    return {
        "min_rows": _int_env("SKILLRA_QUALITY_MIN_ROWS", 100),
        "max_duplicate_share": _float_env("SKILLRA_QUALITY_MAX_DUPLICATE_SHARE", 0.0),
        "min_salary_known_share": _float_env("SKILLRA_QUALITY_MIN_SALARY_KNOWN_SHARE", 0.01),
        "max_unknown_role_share": _float_env("SKILLRA_QUALITY_MAX_UNKNOWN_ROLE_SHARE", 0.80),
        "max_unknown_grade_share": _float_env("SKILLRA_QUALITY_MAX_UNKNOWN_GRADE_SHARE", 0.95),
        "max_unknown_geo_share": _float_env("SKILLRA_QUALITY_MAX_UNKNOWN_GEO_SHARE", 0.95),
        "max_unknown_work_mode_share": _float_env("SKILLRA_QUALITY_MAX_UNKNOWN_WORK_MODE_SHARE", 0.95),
        "min_market_view_rows": _int_env("SKILLRA_QUALITY_MIN_MARKET_VIEW_ROWS", 1),
        "min_segment_rows": _int_env("SKILLRA_QUALITY_MIN_SEGMENT_ROWS", 20),
        "min_segment_salary_known_share": _float_env("SKILLRA_QUALITY_MIN_SEGMENT_SALARY_KNOWN_SHARE", 0.05),
        "trend_min_complete_periods": _int_env("SKILLRA_TREND_MIN_COMPLETE_PERIODS", 8),
        "trend_min_salary_known_share": _float_env("SKILLRA_TREND_MIN_SALARY_KNOWN_SHARE", 0.10),
        "trend_max_duplicate_share": _float_env("SKILLRA_TREND_MAX_DUPLICATE_SHARE", 0.0),
    }


def _gate(
    name: str, passed: bool, value: object, threshold: object, details: object | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "passed": bool(passed),
        "value": value,
        "threshold": threshold,
    }
    if details is not None:
        payload["details"] = details
    return payload


def _first_existing_column(columns: list[str] | tuple[str, ...], candidates: tuple[str, ...]) -> str | None:
    existing = set(columns)
    for candidate in candidates:
        if candidate in existing:
            return candidate
    return None


def _unknown_share(df, column: str | None) -> float:
    if column is None or column not in df.columns or len(df) == 0:
        return 1.0
    normalized = df[column].astype("object").fillna("").astype(str).str.strip().str.lower()
    return float(normalized.isin(UNKNOWN_VALUES).mean())


def _salary_known_share(df) -> float:
    if len(df) == 0:
        return 0.0
    if "salary_known" in df.columns:
        return float(df["salary_known"].fillna(False).astype(bool).mean())
    for column in ("salary_mid_rub_capped", "salary_mid_rub", "salary_mid"):
        if column in df.columns:
            return float(df[column].notna().mean())
    salary_bounds = [column for column in ("salary_from", "salary_to") if column in df.columns]
    if salary_bounds:
        return float(df[salary_bounds].notna().any(axis=1).mean())
    return 0.0


def _compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _market_trust_summary(market_view) -> dict[str, object]:
    """Summarize trust inputs for the processed market dataset."""

    if market_view is None or len(market_view) == 0:
        return {
            "vacancy_count": 0,
            "salary_sample_size": 0,
            "salary_coverage_share": None,
            "confidence_counts": {},
        }
    vacancy_col = "vacancy_count" if "vacancy_count" in market_view.columns else "vacancy_count_total"
    vacancy_count = int(market_view[vacancy_col].fillna(0).sum()) if vacancy_col in market_view.columns else 0
    if "salary_sample_size" in market_view.columns:
        salary_sample_size = int(market_view["salary_sample_size"].fillna(0).sum())
    elif "vacancy_count_salary" in market_view.columns:
        salary_sample_size = int(market_view["vacancy_count_salary"].fillna(0).sum())
    else:
        salary_sample_size = 0
    salary_coverage_share = round(salary_sample_size / vacancy_count, 6) if vacancy_count else None
    confidence_counts = {}
    if "confidence" in market_view.columns:
        confidence_counts = {
            str(key): int(value) for key, value in market_view["confidence"].fillna("unknown").value_counts().items()
        }
    return {
        "vacancy_count": vacancy_count,
        "salary_sample_size": salary_sample_size,
        "salary_coverage_share": salary_coverage_share,
        "confidence_counts": confidence_counts,
    }


def _data_scope_summary(df_features) -> dict[str, object]:
    """Summarize processed source scope and salary disclosure coverage."""

    row_count = int(len(df_features))
    scope_counts: dict[str, int] = {}
    if "dataset_scope" in df_features.columns:
        scope_counts = {
            str(scope): int(count)
            for scope, count in df_features["dataset_scope"].fillna("unknown").value_counts().items()
        }

    if "salary_disclosed" in df_features.columns:
        salary_disclosed_count = int(df_features["salary_disclosed"].fillna(False).astype(bool).sum())
    else:
        salary_disclosed_count = int(round(_salary_known_share(df_features) * row_count))

    return {
        "row_count": row_count,
        "dataset_scope_counts": scope_counts,
        "salary_disclosed_count": salary_disclosed_count,
        "salary_disclosure_share": round(salary_disclosed_count / row_count, 6) if row_count else None,
    }


def _observed_publication_range(df_features) -> dict[str, str | None]:
    column = _first_existing_column(list(df_features.columns), ("published_at_iso", "published_at"))
    if column is None or len(df_features) == 0:
        return {"observed_published_at_from": None, "observed_published_at_to": None}
    parsed_dates = [
        parsed for value in df_features[column].dropna().tolist() if (parsed := parse_date_value(value)) is not None
    ]
    return {
        "observed_published_at_from": min(parsed_dates).isoformat() if parsed_dates else None,
        "observed_published_at_to": max(parsed_dates).isoformat() if parsed_dates else None,
    }


def _lineage_metadata(df_features, ingestion_payload: dict[str, object] | None) -> dict[str, object]:
    ingestion_payload = ingestion_payload or {}
    date_semantics = ingestion_payload.get("date_semantics")
    publication_range = _observed_publication_range(df_features)
    source_kind = (
        ingestion_payload.get("source_kind")
        or ingestion_payload.get("source_mode")
        or ingestion_payload.get("source")
        or "unknown"
    )
    dataset_semantic_type = ingestion_payload.get("dataset_semantic_type")
    if not dataset_semantic_type:
        dataset_semantic_type = (
            "historical_publication_facts"
            if source_kind == "minio_backfill_completed" and date_semantics
            else "current_market_snapshot"
        )
    return {
        "source_kind": str(source_kind),
        "dataset_semantic_type": str(dataset_semantic_type),
        "source_capability_ref": ingestion_payload.get("source_capability_ref")
        if isinstance(ingestion_payload.get("source_capability_ref"), dict)
        else None,
        "requested_date_from": ingestion_payload.get("requested_date_from"),
        "requested_date_to": ingestion_payload.get("requested_date_to"),
        **publication_range,
        "date_semantics_status": date_semantics.get("status") if isinstance(date_semantics, dict) else None,
    }


def _evaluate_quality_gates(df_features, market_view, thresholds: dict[str, float | int] | None = None) -> dict:
    """Evaluate publish-blocking data quality gates for a processed run."""

    resolved_thresholds = {**_quality_thresholds(), **(thresholds or {})}
    row_count = int(len(df_features))
    market_view_rows = int(len(market_view))
    columns = list(df_features.columns)
    id_column = _first_existing_column(columns, ID_COLUMNS)
    missing_required = [column for column in REQUIRED_FEATURE_COLUMNS if column not in df_features.columns]
    missing_contract = missing_required + ([] if id_column else ["vacancy_id|hh_vacancy_id|id"])

    duplicate_count = int(df_features.duplicated(subset=[id_column]).sum()) if id_column else row_count
    duplicate_share = duplicate_count / row_count if row_count else 1.0
    grade_column = (
        "grade_final" if "grade_final" in df_features.columns else "grade" if "grade" in df_features.columns else None
    )
    unknown_role_share = _unknown_share(df_features, "primary_role")
    unknown_grade_share = _unknown_share(df_features, grade_column)
    unknown_geo_share = _unknown_share(df_features, "city_tier")
    unknown_work_mode_share = _unknown_share(df_features, "work_mode")
    salary_known_share = _salary_known_share(df_features)

    gates = [
        _gate("non_empty_features", row_count > 0, row_count, "> 0"),
        _gate("min_rows", row_count >= resolved_thresholds["min_rows"], row_count, resolved_thresholds["min_rows"]),
        _gate("required_columns", not missing_contract, missing_contract, "no missing columns"),
        _gate(
            "duplicate_share",
            duplicate_share <= resolved_thresholds["max_duplicate_share"],
            round(duplicate_share, 6),
            resolved_thresholds["max_duplicate_share"],
            {"duplicate_count": duplicate_count, "id_column": id_column},
        ),
        _gate(
            "salary_known_share",
            salary_known_share >= resolved_thresholds["min_salary_known_share"],
            round(salary_known_share, 6),
            resolved_thresholds["min_salary_known_share"],
        ),
        _gate(
            "unknown_role_share",
            unknown_role_share <= resolved_thresholds["max_unknown_role_share"],
            round(unknown_role_share, 6),
            resolved_thresholds["max_unknown_role_share"],
        ),
        _gate(
            "unknown_grade_share",
            unknown_grade_share <= resolved_thresholds["max_unknown_grade_share"],
            round(unknown_grade_share, 6),
            resolved_thresholds["max_unknown_grade_share"],
            {"grade_column": grade_column},
        ),
        _gate(
            "unknown_geo_share",
            unknown_geo_share <= resolved_thresholds["max_unknown_geo_share"],
            round(unknown_geo_share, 6),
            resolved_thresholds["max_unknown_geo_share"],
        ),
        _gate(
            "unknown_work_mode_share",
            unknown_work_mode_share <= resolved_thresholds["max_unknown_work_mode_share"],
            round(unknown_work_mode_share, 6),
            resolved_thresholds["max_unknown_work_mode_share"],
        ),
        _gate(
            "min_market_view_rows",
            market_view_rows >= resolved_thresholds["min_market_view_rows"],
            market_view_rows,
            resolved_thresholds["min_market_view_rows"],
        ),
    ]
    failed = [gate["name"] for gate in gates if not gate["passed"]]
    return {
        "status": "passed" if not failed else "failed",
        "failed_gates": failed,
        "thresholds": resolved_thresholds,
        "metrics": {
            "features_rows": row_count,
            "market_view_rows": market_view_rows,
            "duplicate_count": duplicate_count,
            "duplicate_share": round(duplicate_share, 6),
            "salary_known_share": round(salary_known_share, 6),
            "unknown_role_share": round(unknown_role_share, 6),
            "unknown_grade_share": round(unknown_grade_share, 6),
            "unknown_geo_share": round(unknown_geo_share, 6),
            "unknown_work_mode_share": round(unknown_work_mode_share, 6),
            "id_column": id_column,
            "grade_column": grade_column,
        },
        "gates": gates,
    }


def _segment_quality_report(df_features, thresholds: dict[str, float | int] | None = None) -> dict[str, object]:
    resolved_thresholds = {**_quality_thresholds(), **(thresholds or {})}
    min_segment_rows = int(resolved_thresholds["min_segment_rows"])
    min_salary_share = float(resolved_thresholds["min_segment_salary_known_share"])
    dimensions: dict[str, list[dict[str, object]]] = {}
    low_confidence_segments: list[dict[str, object]] = []

    for column in SEGMENT_GATE_COLUMNS:
        if column not in df_features.columns:
            continue
        values = df_features[column].astype("object").fillna("unknown").astype(str)
        column_segments: list[dict[str, object]] = []
        for value, group in df_features.assign(_segment_value=values).groupby("_segment_value", dropna=False):
            row_count = int(len(group))
            salary_share = _salary_known_share(group)
            unknown_value = str(value).strip().lower() in UNKNOWN_VALUES
            passed = row_count >= min_segment_rows and salary_share >= min_salary_share and not unknown_value
            segment = {
                "dimension": column,
                "value": str(value),
                "row_count": row_count,
                "salary_known_share": round(salary_share, 6),
                "confidence": "usable" if passed else "low",
                "passed": passed,
            }
            column_segments.append(segment)
            if not passed:
                low_confidence_segments.append(segment)
        dimensions[column] = sorted(column_segments, key=lambda item: (-int(item["row_count"]), str(item["value"])))

    return {
        "status": "passed" if not low_confidence_segments else "warning",
        "thresholds": {
            "min_segment_rows": min_segment_rows,
            "min_segment_salary_known_share": min_salary_share,
        },
        "dimensions": dimensions,
        "low_confidence_segment_count": len(low_confidence_segments),
        "low_confidence_segments": low_confidence_segments[:50],
    }


def _observed_complete_period_count(df_features) -> int:
    column = _first_existing_column(list(df_features.columns), ("published_at_iso", "published_at"))
    if column is None or len(df_features) == 0:
        return 0
    periods = {
        f"{parsed.isocalendar().year}-W{parsed.isocalendar().week:02d}"
        for value in df_features[column].dropna().tolist()
        if (parsed := parse_date_value(value)) is not None
    }
    return len(periods)


def _trend_gate_criterion(
    name: str,
    passed: bool,
    value: object,
    threshold: object | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"name": name, "passed": bool(passed), "value": value}
    if threshold is not None:
        payload["threshold"] = threshold
    return payload


def _metric_float(metrics: dict[str, object], key: str, default: float) -> float:
    value = metrics.get(key)
    if value is None:
        return default
    return float(value)


def _evaluate_trend_ready_gate(
    df_features,
    quality_gates: dict[str, object],
    segment_report: dict[str, object],
    lineage: dict[str, object],
    thresholds: dict[str, float | int] | None = None,
) -> dict[str, object]:
    resolved_thresholds = {**_quality_thresholds(), **(thresholds or {})}
    metrics = quality_gates.get("metrics") if isinstance(quality_gates.get("metrics"), dict) else {}
    duplicate_share = _metric_float(metrics, "duplicate_share", 1.0)
    salary_share = _metric_float(metrics, "salary_known_share", 0.0)
    period_count = _observed_complete_period_count(df_features)
    source_ref_failures = validate_source_capability_ref(
        lineage.get("source_capability_ref"),
        expected_use_case="historical_collection",
        require_supported=True,
    )
    criteria = [
        _trend_gate_criterion(
            "processed_quality_passed",
            quality_gates.get("status") == "passed",
            quality_gates.get("status"),
        ),
        _trend_gate_criterion(
            "historical_publication_facts",
            lineage.get("dataset_semantic_type") == "historical_publication_facts",
            lineage.get("dataset_semantic_type"),
        ),
        _trend_gate_criterion(
            "date_semantics_passed",
            lineage.get("date_semantics_status") == "passed",
            lineage.get("date_semantics_status"),
        ),
        _trend_gate_criterion(
            "source_capability_supported",
            not source_ref_failures,
            source_ref_failures or "supported",
        ),
        _trend_gate_criterion(
            "min_complete_periods",
            period_count >= int(resolved_thresholds["trend_min_complete_periods"]),
            period_count,
            int(resolved_thresholds["trend_min_complete_periods"]),
        ),
        _trend_gate_criterion(
            "duplicate_share",
            duplicate_share <= float(resolved_thresholds["trend_max_duplicate_share"]),
            round(duplicate_share, 6),
            float(resolved_thresholds["trend_max_duplicate_share"]),
        ),
        _trend_gate_criterion(
            "salary_known_share",
            salary_share >= float(resolved_thresholds["trend_min_salary_known_share"]),
            round(salary_share, 6),
            float(resolved_thresholds["trend_min_salary_known_share"]),
        ),
        _trend_gate_criterion(
            "segment_coverage",
            segment_report.get("status") == "passed",
            segment_report.get("status"),
            "passed",
        ),
    ]
    failed = [str(item["name"]) for item in criteria if not item["passed"]]
    eligible = not failed
    return {
        "gate_version": TREND_READY_GATE_VERSION,
        "status": "passed" if eligible else "blocked",
        "eligible": eligible,
        "failed_criteria": failed,
        "criteria": criteria,
        "metrics": {
            "complete_periods": period_count,
            "duplicate_share": round(duplicate_share, 6),
            "salary_known_share": round(salary_share, 6),
            "low_confidence_segment_count": segment_report.get("low_confidence_segment_count"),
        },
        "thresholds": {
            "min_complete_periods": int(resolved_thresholds["trend_min_complete_periods"]),
            "max_duplicate_share": float(resolved_thresholds["trend_max_duplicate_share"]),
            "min_salary_known_share": float(resolved_thresholds["trend_min_salary_known_share"]),
            "segment_coverage": "passed",
        },
        "reason_code": "trend_ready" if eligible else "trend_ready_gate_failed",
        "reason": "trend-ready gates passed" if eligible else "trend-ready gates not passed",
        "user_message": None if eligible else TREND_BLOCKED_USER_MESSAGE,
    }


def _product_eligibility(
    quality_gates: dict[str, object],
    segment_report: dict[str, object],
    lineage: dict[str, object],
    trend_ready_gate: dict[str, object] | None = None,
) -> dict[str, object]:
    metrics = quality_gates.get("metrics") if isinstance(quality_gates.get("metrics"), dict) else {}
    quality_passed = quality_gates.get("status") == "passed"
    salary_share = _metric_float(metrics, "salary_known_share", 0.0)
    role_unknown = _metric_float(metrics, "unknown_role_share", 1.0)
    grade_unknown = _metric_float(metrics, "unknown_grade_share", 1.0)
    segment_status = str(segment_report.get("status") or "unknown")
    trend_ready = bool(trend_ready_gate and trend_ready_gate.get("eligible") is True)
    trend_reason = str((trend_ready_gate or {}).get("reason") or "historical trend-readiness gates not passed")
    trend_reason_code = str((trend_ready_gate or {}).get("reason_code") or "trend_ready_gate_failed")
    return {
        "search": {
            "eligible": quality_passed,
            "reason": "processed quality gates passed" if quality_passed else "processed quality gates failed",
        },
        "salary": {
            "eligible": quality_passed and salary_share >= 0.10,
            "coverage_share": round(salary_share, 6),
            "reason": "salary coverage is usable" if salary_share >= 0.10 else "salary coverage is too low",
        },
        "trends": {
            "eligible": trend_ready,
            "gate_version": (trend_ready_gate or {}).get("gate_version"),
            "reason_code": "trend_ready" if trend_ready else trend_reason_code,
            "reason": "trend-ready gates passed" if trend_ready else trend_reason,
            "user_message": None
            if trend_ready
            else (trend_ready_gate or {}).get("user_message", TREND_BLOCKED_USER_MESSAGE),
            "failed_criteria": (trend_ready_gate or {}).get("failed_criteria", []),
        },
        "recommendations": {
            "eligible": quality_passed and role_unknown <= 0.50 and grade_unknown <= 0.50,
            "segment_gate_status": segment_status,
            "reason": "role and grade coverage are usable"
            if role_unknown <= 0.50 and grade_unknown <= 0.50
            else "role or grade coverage is too weak",
        },
    }


def _artifact_descriptor(path: Path, *, artifact_type: str, lake_key: str | None = None) -> dict[str, object]:
    return {
        "type": artifact_type,
        "path": str(path),
        "lake_key": lake_key,
        "sha256": _compute_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _build_run_manifest(
    *,
    run_id: str,
    run_timestamp: datetime,
    dataset_meta: dict[str, object],
    artifacts: tuple[Path, ...],
    ingestion_payload: dict[str, object] | None,
) -> dict[str, object]:
    artifact_types = {
        "hh_clean.parquet": "bronze_clean",
        "hh_features.parquet": "silver_features",
        "market_view.parquet": "gold_market_view",
        "dataset_meta.json": "dataset_meta",
        "quality_report.json": "quality_report",
    }
    descriptors = []
    for path in artifacts:
        filename = path.name
        artifact_type = artifact_types.get(filename, filename)
        lake_key = None
        if filename == "hh_clean.parquet":
            lake_key = f"hh/bronze/run={run_id}/hh_clean.parquet"
        elif filename == "hh_features.parquet":
            lake_key = f"hh/silver/run={run_id}/hh_features.parquet"
        elif filename == "market_view.parquet":
            lake_key = f"hh/gold/run={run_id}/market_view.parquet"
        elif filename == "dataset_meta.json":
            lake_key = f"hh/manifests/run={run_id}/dataset_meta.json"
        elif filename == "quality_report.json":
            lake_key = f"hh/manifests/run={run_id}/quality_report.json"
        descriptors.append(_artifact_descriptor(path, artifact_type=artifact_type, lake_key=lake_key))

    raw_quality_report = dataset_meta.get("raw_quality_report")
    raw_quality_status = raw_quality_report.get("status") if isinstance(raw_quality_report, dict) else None
    processed_quality_report = dataset_meta.get("processed_quality_report")
    processed_quality_status = (
        processed_quality_report.get("status") if isinstance(processed_quality_report, dict) else None
    )
    quality_gates = dataset_meta.get("quality_gates")
    failed_processed_gates = quality_gates.get("failed_gates", []) if isinstance(quality_gates, dict) else []
    return {
        "manifest_schema_version": "2",
        "run_id": run_id,
        "generated_at_utc": run_timestamp.isoformat(),
        "git_sha": os.getenv("SKILLRA_GIT_SHA") or os.getenv("GIT_SHA") or "unknown",
        "source": dataset_meta.get("source_kind"),
        "source_lineage": {
            "source_kind": dataset_meta.get("source_kind"),
            "dataset_semantic_type": dataset_meta.get("dataset_semantic_type"),
            "requested_date_from": dataset_meta.get("requested_date_from"),
            "requested_date_to": dataset_meta.get("requested_date_to"),
            "observed_published_at_from": dataset_meta.get("observed_published_at_from"),
            "observed_published_at_to": dataset_meta.get("observed_published_at_to"),
            "date_semantics_status": dataset_meta.get("date_semantics_status"),
            "source_capability_ref": dataset_meta.get("source_capability_ref"),
            "ingestion": ingestion_payload or {},
        },
        "raw_run_id": (ingestion_payload or {}).get("last_run_id"),
        "processed_run_id": run_id,
        "collector_schema_version": (ingestion_payload or {}).get("schema_version"),
        "processed_schema_version": "1",
        "features_rows": dataset_meta.get("features_rows"),
        "market_view_rows": dataset_meta.get("market_view_rows"),
        "quality_decision": {
            "raw_status": raw_quality_status,
            "processed_status": processed_quality_status,
            "failed_processed_gates": failed_processed_gates,
            "product_eligibility": dataset_meta.get("product_eligibility"),
            "trend_ready_gate": dataset_meta.get("trend_ready_gate"),
        },
        "publish_decision": {
            "state": "candidate",
            "latest_eligible": processed_quality_status == "passed",
            "quality_report_path": str(dataset_meta.get("quality_report_path") or ""),
        },
        "serving_consumers": {
            "api_datastore": {"artifact": "hh_features.parquet", "status": "planned_after_reload"},
            "postgres_vacancy_snapshots": {"status": "planned_after_reload"},
            "meilisearch": {"status": "planned_after_reload"},
        },
        "product_eligibility": dataset_meta.get("product_eligibility"),
        "artifacts": descriptors,
    }


def _publish_latest_if_quality_passed(
    latest_dir: Path,
    run_dir: Path,
    artifacts: tuple[Path, ...],
    quality_gates: dict,
) -> None:
    """Publish latest only when all quality gates pass."""

    if quality_gates.get("status") != "passed":
        failed = ", ".join(str(name) for name in quality_gates.get("failed_gates", []))
        raise RuntimeError(f"Data quality gates failed: {failed}")
    _update_latest_dir(latest_dir, run_dir, artifacts)


def _update_latest_dir(latest_dir: Path, run_dir: Path, artifacts: tuple[Path, ...]) -> None:
    """Point latest at run_dir with a portable symlink, falling back to copies."""

    if latest_dir.exists() or latest_dir.is_symlink():
        if latest_dir.is_symlink() or latest_dir.is_file():
            latest_dir.unlink()
        else:
            shutil.rmtree(latest_dir)
    try:
        symlink_target = Path(os.path.relpath(run_dir, latest_dir.parent))
        latest_dir.symlink_to(symlink_target, target_is_directory=True)
    except OSError:
        latest_dir.mkdir(parents=True, exist_ok=True)
        for artifact in artifacts:
            shutil.copy2(artifact, latest_dir / artifact.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-data-file",
        default=config.RAW_DATA_FILE,
        help="Path to the raw CSV file used as pipeline input.",
    )
    parser.add_argument(
        "--dataset-meta-extra",
        type=Path,
        help="Optional JSON file to merge into dataset_meta under the 'ingestion' key.",
    )
    parser.add_argument(
        "--raw-quality-report",
        type=Path,
        help="Optional raw quality report JSON produced by scripts/raw_hh_gate.py.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional explicit run id. Used by pipeline_runner to align DB data_runs and dataset_meta.",
    )
    return parser.parse_args()


def _resolve_run_id(explicit_run_id: str | None, run_timestamp: datetime) -> str:
    if explicit_run_id is None:
        return run_timestamp.strftime("%Y%m%dT%H%M%SZ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", explicit_run_id):
        raise ValueError("run id must contain only letters, digits, dots, underscores or dashes")
    return explicit_run_id


def main() -> None:
    """Load raw data, clean it, engineer features, and persist outputs."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    config.ensure_directories()
    run_timestamp = datetime.now(timezone.utc)
    run_id = _resolve_run_id(args.run_id, run_timestamp)
    run_dir = config.PROCESSED_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_path = Path(args.raw_data_file)
    clean_path = run_dir / "hh_clean.parquet"
    feature_path = run_dir / "hh_features.parquet"
    market_view_path = run_dir / "market_view.parquet"
    snapshots_dir = config.PROCESSED_DATA_DIR / "market_snapshots"
    ingestion_payload = None
    if args.dataset_meta_extra:
        ingestion_payload = json.loads(args.dataset_meta_extra.read_text(encoding="utf-8"))
    raw_quality_report = None
    if args.raw_quality_report:
        raw_quality_report = json.loads(args.raw_quality_report.read_text(encoding="utf-8"))

    df_raw = io.load_raw(raw_path)
    df_clean = cleaning.handle_missingness(df_raw, drop_threshold=cleaning.LOW_INFORMATION_THRESHOLD)
    df_clean = cleaning.parse_dates(df_clean)
    df_clean = cleaning.salary_prepare(df_clean)
    df_clean = cleaning.deduplicate(df_clean)
    io.save_processed(df_clean, clean_path)

    df_features = features.assemble_features(df_clean.copy())
    io.save_processed(df_features, feature_path)

    market_view = market.build_market_view(df_features.copy())
    io.save_processed(market_view, market_view_path)
    snapshot_path = timeseries.build_weekly_snapshot(feature_path, snapshots_dir, week_start=run_timestamp.date())

    dataset_meta_path = run_dir / "dataset_meta.json"
    quality_report_path = run_dir / "quality_report.json"
    run_manifest_path = run_dir / "run_manifest.json"
    lineage = _lineage_metadata(df_features, ingestion_payload)
    quality_gates = _evaluate_quality_gates(df_features, market_view)
    segment_report = _segment_quality_report(df_features)
    trend_ready_gate = _evaluate_trend_ready_gate(df_features, quality_gates, segment_report, lineage)
    product_eligibility = _product_eligibility(quality_gates, segment_report, lineage, trend_ready_gate)
    processed_quality_report = {
        "status": quality_gates["status"],
        "generated_at_utc": run_timestamp.isoformat(),
        "quality_gates": quality_gates,
        "segment_gates": segment_report,
        "trend_ready_gate": trend_ready_gate,
        "product_eligibility": product_eligibility,
    }
    dataset_meta = {
        "run_id": run_id,
        "generated_at_utc": run_timestamp.isoformat(),
        "features_rows": len(df_features),
        "market_view_rows": len(market_view),
        "data_scope": _data_scope_summary(df_features),
        "market_trust": _market_trust_summary(market_view),
        "features_path": str(feature_path),
        "market_view_path": str(market_view_path),
        "market_snapshot_path": str(snapshot_path),
        "quality_report_path": str(quality_report_path),
        "run_manifest_path": str(run_manifest_path),
    }
    dataset_meta.update(lineage)
    dataset_meta["quality_gates"] = quality_gates
    dataset_meta["processed_quality_report"] = processed_quality_report
    dataset_meta["trend_ready_gate"] = trend_ready_gate
    dataset_meta["product_eligibility"] = product_eligibility
    if raw_quality_report is not None:
        dataset_meta["raw_quality_report"] = raw_quality_report
    if ingestion_payload is not None:
        if "ingestion" in dataset_meta:
            raise ValueError("dataset_meta already contains 'ingestion' key.")
        dataset_meta["ingestion"] = ingestion_payload
    dataset_meta_path.write_text(json.dumps(dataset_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    quality_report_payload = {
        "run_id": run_id,
        "generated_at_utc": run_timestamp.isoformat(),
        "raw": raw_quality_report,
        "processed": processed_quality_report,
    }
    quality_report_path.write_text(json.dumps(quality_report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    run_manifest = _build_run_manifest(
        run_id=run_id,
        run_timestamp=run_timestamp,
        dataset_meta=dataset_meta,
        artifacts=(clean_path, feature_path, market_view_path, dataset_meta_path, quality_report_path),
        ingestion_payload=ingestion_payload,
    )
    run_manifest_path.write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_dir = config.PROCESSED_LATEST_DIR
    _publish_latest_if_quality_passed(
        latest_dir,
        run_dir,
        (clean_path, feature_path, market_view_path, dataset_meta_path, quality_report_path, run_manifest_path),
        quality_gates,
    )

    logger.info("Saved clean dataset to %s", clean_path)
    logger.info("Saved feature dataset to %s", feature_path)
    logger.info("Saved market view to %s", market_view_path)
    logger.info("Saved market snapshot to %s", snapshot_path)
    logger.info("Updated latest processed data to %s", latest_dir)


if __name__ == "__main__":
    main()
