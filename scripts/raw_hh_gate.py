from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.s3_sync_raw_hh import build_raw_hh_artifacts, load_state_json, s3_object_exists
from skillra_pda.ingest.date_semantics import evaluate_csv_date_semantics
from skillra_pda.ingest.source_registry import validate_source_capability_ref
from skillra_pda.storage.s3_client import create_s3_client, download_bytes

RAW_ID_COLUMNS = ("vacancy_id", "hh_vacancy_id", "id")
CRITICAL_RAW_FIELDS = (
    "title",
    "vacancy_id",
    "hh_vacancy_id",
    "id",
    "url",
    "vacancy_url",
    "published_at_iso",
    "published_at",
)
CRITICAL_FIELD_GROUPS = {
    "title": ("title",),
    "id": RAW_ID_COLUMNS,
    "url": ("url", "vacancy_url"),
    "published_at": ("published_at_iso", "published_at"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate raw HH artifacts before processing/publish.")
    parser.add_argument(
        "--storage-dir",
        default=str(Path("data") / "raw" / "hh"),
        help="Base raw HH storage directory (default: data/raw/hh).",
    )
    parser.add_argument(
        "--state-path",
        default=None,
        help="Override path to state.json (default: <storage-dir>/state.json).",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=int(os.environ.get("SKILLRA_RAW_HH_MIN_ROWS", "1")),
        help="Minimum accepted raw rows (default: SKILLRA_RAW_HH_MIN_ROWS or 1).",
    )
    parser.add_argument(
        "--max-removed-share",
        type=float,
        default=float(os.environ.get("SKILLRA_RAW_HH_MAX_REMOVED_SHARE", "0.80")),
        help="Maximum removed_count/previous_row_count share when previous_row_count can be inferred.",
    )
    parser.add_argument(
        "--require-s3",
        action="store_true",
        help="Require run-scoped raw objects and latest_pointer.json to exist in S3/MinIO.",
    )
    parser.add_argument(
        "--require-date-semantics",
        action="store_true",
        help="Require raw rows to have publication dates inside the requested date window.",
    )
    parser.add_argument(
        "--date-window-from",
        default=None,
        help="Requested publication date lower bound, inclusive: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--date-window-to",
        default=None,
        help="Requested publication date upper bound, inclusive: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--max-date-unknown-share",
        type=float,
        default=float(os.environ.get("SKILLRA_RAW_HH_MAX_DATE_UNKNOWN_SHARE", "0.05")),
        help="Maximum accepted share of rows without parsed publication date.",
    )
    parser.add_argument(
        "--max-date-out-of-window-share",
        type=float,
        default=float(os.environ.get("SKILLRA_RAW_HH_MAX_DATE_OUT_OF_WINDOW_SHARE", "0.0")),
        help="Maximum accepted share of rows outside the requested publication date window.",
    )
    parser.add_argument(
        "--min-critical-field-completeness",
        type=float,
        default=float(os.environ.get("SKILLRA_RAW_HH_MIN_CRITICAL_FIELD_COMPLETENESS", "0.95")),
        help="Minimum completeness for title/id/url/published_at raw field groups.",
    )
    parser.add_argument(
        "--max-zero-row-shards",
        type=int,
        default=int(os.environ.get("SKILLRA_RAW_HH_MAX_ZERO_ROW_SHARDS", "0")),
        help="Maximum accepted collection shards that returned zero rows when shard reports exist.",
    )
    parser.add_argument(
        "--max-collection-error-share",
        type=float,
        default=float(os.environ.get("SKILLRA_RAW_HH_MAX_COLLECTION_ERROR_SHARE", "0.0")),
        help="Maximum accepted share of collection shards with errors.",
    )
    parser.add_argument(
        "--min-collection-success-share",
        type=float,
        default=float(os.environ.get("SKILLRA_RAW_HH_MIN_COLLECTION_SUCCESS_SHARE", "1.0")),
        help="Minimum accepted share of successful collection shards when shard reports exist.",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help="Override S3 bucket (default: S3_BUCKET_RAW_HH env).",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Write a standalone raw quality report JSON to this path.",
    )
    return parser.parse_args()


def validate_local_raw_hh(
    storage_dir: Path,
    state: dict,
    *,
    min_rows: int,
    max_removed_share: float,
    require_date_semantics: bool = False,
    date_window_from: str | None = None,
    date_window_to: str | None = None,
    max_date_unknown_share: float = 0.05,
    max_date_out_of_window_share: float = 0.0,
    min_critical_field_completeness: float = 0.95,
    max_zero_row_shards: int = 0,
    max_collection_error_share: float = 0.0,
    min_collection_success_share: float = 1.0,
) -> dict:
    row_count = int(state.get("row_count") or 0)
    new_count = int(state.get("new_count") or 0)
    removed_count = int(state.get("removed_count") or 0)
    previous_row_count = row_count - new_count + removed_count

    failures: list[str] = []
    if row_count < min_rows:
        failures.append(f"row_count {row_count} < min_rows {min_rows}")

    dataset_scope = state.get("dataset_scope")
    if dataset_scope not in {"all_vacancies", "salary_disclosed"}:
        failures.append("dataset_scope must be all_vacancies or salary_disclosed")
    if not isinstance(state.get("salary_only"), bool):
        failures.append("salary_only must be present as boolean")
    source_capability_ref = state.get("source_capability_ref")
    requested_from = date_window_from or state.get("requested_date_from") or state.get("date_window_from")
    requested_to = date_window_to or state.get("requested_date_to") or state.get("date_window_to")
    use_case = (
        "historical_collection"
        if state.get("dataset_semantic_type") == "historical_publication_facts" or (requested_from and requested_to)
        else "current_snapshot"
    )
    if requested_from and requested_to:
        use_case = "historical_collection"
    source_ref_failures = validate_source_capability_ref(
        source_capability_ref,
        expected_use_case=use_case,
        expected_dataset_scope=str(dataset_scope) if dataset_scope is not None else None,
        expected_salary_only=state.get("salary_only") if isinstance(state.get("salary_only"), bool) else None,
        require_supported=True,
    )
    failures.extend(f"source_capability_ref: {failure}" for failure in source_ref_failures)

    if previous_row_count > 0:
        removed_share = removed_count / previous_row_count
        if removed_share > max_removed_share:
            failures.append(f"removed_share {removed_share:.4f} > max_removed_share {max_removed_share:.4f}")
    else:
        removed_share = 0.0

    missing_files = []
    for artifact in build_raw_hh_artifacts(storage_dir, state, legacy_root_keys=False):
        if not artifact.local_path.exists():
            missing_files.append(str(artifact.local_path))
    if missing_files:
        failures.append("missing local files: " + ", ".join(missing_files))

    latest_csv = resolve_latest_csv(storage_dir, state)
    expected_sha = state.get("sha256")
    actual_sha = None
    if expected_sha and latest_csv.exists():
        actual_sha = compute_sha256(latest_csv)
        if actual_sha != expected_sha:
            failures.append(f"latest.csv sha256 mismatch: {actual_sha} != {expected_sha}")
    csv_quality = raw_csv_quality(latest_csv) if latest_csv.exists() else {"status": "missing", "row_count": 0}
    duplicate_share = float(csv_quality.get("duplicate_share") or 0.0)
    max_duplicate_share = float(os.environ.get("SKILLRA_RAW_HH_MAX_DUPLICATE_SHARE", "0.20"))
    if duplicate_share > max_duplicate_share:
        failures.append(f"duplicate_share {duplicate_share:.4f} > max_duplicate_share {max_duplicate_share:.4f}")
    csv_row_count = int(csv_quality.get("row_count") or 0)
    if csv_quality.get("status") == "parsed" and csv_row_count != row_count:
        failures.append(f"latest.csv row_count {csv_row_count} != state row_count {row_count}")
    critical_completeness = critical_field_group_completeness(csv_quality)
    for group_name, completeness in critical_completeness.items():
        if completeness < min_critical_field_completeness:
            failures.append(
                f"{group_name}_completeness {completeness:.4f} "
                f"< min_critical_field_completeness {min_critical_field_completeness:.4f}"
            )

    if require_date_semantics and not (requested_from and requested_to):
        requested_from = requested_from or state.get("date_from")
        requested_to = requested_to or state.get("date_to")
    date_semantics = None
    if requested_from and requested_to:
        try:
            latest_csv = resolve_latest_csv(storage_dir, state)
            date_semantics = evaluate_csv_date_semantics(
                latest_csv,
                requested_date_from=requested_from,
                requested_date_to=requested_to,
                max_unknown_share=max_date_unknown_share,
                max_out_of_window_share=max_date_out_of_window_share,
            )
            if date_semantics.get("status") != "passed":
                detail = "; ".join(str(item) for item in date_semantics.get("failures") or [])
                failures.append("date semantics failed: " + detail)
        except Exception as exc:  # noqa: BLE001 - validation must report all gate failures
            failures.append(f"date semantics failed: {exc}")
            date_semantics = {
                "status": "failed",
                "failures": [str(exc)],
                "requested_date_from": str(requested_from),
                "requested_date_to": str(requested_to),
            }
    elif require_date_semantics:
        failures.append("date semantics window is required")
        date_semantics = {
            "status": "failed",
            "failures": ["date semantics window is required"],
        }

    collector_quality = collection_quality(storage_dir, state)
    if collector_quality.get("status") == "failed":
        failures.append("collection report status failed")
    if int(collector_quality.get("blocked_shards") or 0) > 0:
        failures.append("collection report contains blocked shards")
    if int(collector_quality.get("shard_count") or 0) > 0:
        zero_row_shards = int(collector_quality.get("zero_row_shards") or 0)
        if zero_row_shards > max_zero_row_shards:
            failures.append(f"zero_row_shards {zero_row_shards} > max_zero_row_shards {max_zero_row_shards}")
        error_share = float(collector_quality.get("error_share") or 0.0)
        if error_share > max_collection_error_share:
            failures.append(
                f"collection_error_share {error_share:.4f} > max_collection_error_share "
                f"{max_collection_error_share:.4f}"
            )
        success_share = float(collector_quality.get("success_share") or 0.0)
        if success_share < min_collection_success_share:
            failures.append(
                f"collection_success_share {success_share:.4f} < min_collection_success_share "
                f"{min_collection_success_share:.4f}"
            )

    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "metrics": {
            "row_count": row_count,
            "new_count": new_count,
            "removed_count": removed_count,
            "previous_row_count": previous_row_count,
            "removed_share": round(removed_share, 6),
            "duplicate_count": csv_quality.get("duplicate_count"),
            "duplicate_share": csv_quality.get("duplicate_share"),
            "min_rows": min_rows,
            "dataset_scope": dataset_scope,
            "salary_only": state.get("salary_only"),
            "sha256": actual_sha,
            "expected_sha256": expected_sha,
            "critical_field_group_completeness": critical_completeness,
            "min_critical_field_completeness": min_critical_field_completeness,
            "source_capability_ref": source_capability_ref,
        },
        "csv_quality": csv_quality,
        "collection_quality": collector_quality,
        "date_semantics": date_semantics,
    }


def resolve_latest_csv(storage_dir: Path, state: dict) -> Path:
    latest_path = state.get("latest_path")
    if isinstance(latest_path, str) and latest_path:
        candidate = storage_dir / latest_path
        if candidate.exists():
            return candidate
    return storage_dir / "latest.csv"


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raw_csv_quality(path: Path) -> dict:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        id_column = next((column for column in RAW_ID_COLUMNS if column in fieldnames), None)
        row_count = 0
        ids: list[str] = []
        non_empty_by_field = Counter()
        for row in reader:
            row_count += 1
            if id_column:
                ids.append(str(row.get(id_column) or "").strip())
            for field in CRITICAL_RAW_FIELDS:
                if field in row and str(row.get(field) or "").strip():
                    non_empty_by_field[field] += 1

    duplicate_count = 0
    if id_column:
        counts = Counter(value for value in ids if value)
        duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    completeness = {
        field: round(non_empty_by_field[field] / row_count, 6) if row_count and field in fieldnames else None
        for field in CRITICAL_RAW_FIELDS
    }
    return {
        "status": "parsed",
        "path": str(path),
        "row_count": row_count,
        "id_column": id_column,
        "duplicate_count": duplicate_count,
        "duplicate_share": round(duplicate_count / row_count, 6) if row_count else 0.0,
        "critical_field_completeness": completeness,
    }


def critical_field_group_completeness(csv_quality: dict) -> dict[str, float]:
    completeness = csv_quality.get("critical_field_completeness")
    if not isinstance(completeness, dict):
        return {name: 0.0 for name in CRITICAL_FIELD_GROUPS}
    return {
        name: max(float(completeness.get(field) or 0.0) for field in fields)
        for name, fields in CRITICAL_FIELD_GROUPS.items()
    }


def collection_quality(storage_dir: Path, state: dict) -> dict:
    report_rel = state.get("collection_report_path")
    if not isinstance(report_rel, str) or not report_rel:
        return {
            "status": "not_available",
            "shard_count": 0,
            "successful_shards": 0,
            "error_shards": 0,
            "blocked_shards": 0,
            "zero_row_shards": 0,
        }
    report_path = storage_dir / report_rel
    if not report_path.exists():
        return {"status": "missing", "path": str(report_path)}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    shards = report.get("shard_results") if isinstance(report, dict) else None
    if not isinstance(shards, list):
        shards = []
    error_shards = 0
    blocked_shards = 0
    zero_row_shards = 0
    for shard in shards:
        if not isinstance(shard, dict):
            continue
        errors = [str(error).lower() for error in shard.get("errors") or []]
        if errors:
            error_shards += 1
        if any(token in error for error in errors for token in ("captcha", "blocked", "429", "403")):
            blocked_shards += 1
        if int(shard.get("records_collected") or 0) == 0:
            zero_row_shards += 1
    return {
        "status": str(report.get("status") or "unknown") if isinstance(report, dict) else "invalid",
        "path": str(report_path),
        "source_mode": report.get("source_mode") if isinstance(report, dict) else None,
        "adapter_name": report.get("adapter_name") if isinstance(report, dict) else None,
        "shard_count": len(shards),
        "successful_shards": len(shards) - error_shards,
        "error_shards": error_shards,
        "blocked_shards": blocked_shards,
        "zero_row_shards": zero_row_shards,
        "success_share": round((len(shards) - error_shards) / len(shards), 6) if shards else None,
        "error_share": round(error_shards / len(shards), 6) if shards else None,
        "errors": report.get("errors", []) if isinstance(report, dict) else [],
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def validate_s3_raw_hh(client, bucket: str, storage_dir: Path, state: dict) -> dict:
    artifacts = build_raw_hh_artifacts(storage_dir, state, legacy_root_keys=False)
    missing = [artifact.key for artifact in artifacts if not s3_object_exists(client, bucket, artifact.key)]
    if not s3_object_exists(client, bucket, "latest_pointer.json"):
        missing.append("latest_pointer.json")
        pointer_failures = []
    else:
        pointer_payload = download_bytes(client, bucket, "latest_pointer.json")
        pointer = load_pointer_json(pointer_payload, label="latest_pointer.json")
        pointer_failures = validate_pointer_artifacts(
            client,
            bucket,
            pointer,
            expected_run_id=str(state.get("last_run_id") or ""),
        )
        pointer_keys = {
            str(artifact.get("key") or "") for artifact in pointer.get("artifacts", []) if isinstance(artifact, dict)
        }
        expected_keys = {artifact.key for artifact in artifacts}
        missing_pointer_keys = sorted(expected_keys - pointer_keys)
        if missing_pointer_keys:
            pointer_failures.append("latest_pointer.json missing artifact keys: " + ", ".join(missing_pointer_keys))
    return {
        "status": "passed" if not missing and not pointer_failures else "failed",
        "missing": missing,
        "pointer_failures": pointer_failures,
        "bucket": bucket,
    }


def load_pointer_json(payload: bytes, *, label: str) -> dict:
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def validate_pointer_artifacts(client, bucket: str, pointer: dict, *, expected_run_id: str) -> list[str]:
    failures: list[str] = []
    run_id = str(pointer.get("run_id") or "")
    if not run_id:
        failures.append("latest_pointer.json missing run_id")
    elif expected_run_id and run_id != expected_run_id:
        failures.append(f"latest_pointer.json run_id {run_id} != state last_run_id {expected_run_id}")

    artifacts = pointer.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        failures.append("latest_pointer.json artifacts must be a non-empty list")
        return failures

    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(f"artifact[{index}] must be an object")
            continue
        key = str(artifact.get("key") or "")
        sha256 = str(artifact.get("sha256") or "")
        size_bytes = artifact.get("size_bytes")
        if not key:
            failures.append(f"artifact[{index}] missing key")
            continue
        if run_id and not key.startswith(f"runs/{run_id}/"):
            failures.append(f"artifact[{index}] key is not run-scoped: {key}")
        if not sha256:
            failures.append(f"artifact[{index}] missing sha256: {key}")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            failures.append(f"artifact[{index}] has invalid size_bytes: {key}")
        try:
            payload = download_bytes(client, bucket, key)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"artifact[{index}] download failed: {key}: {exc}")
            continue
        if isinstance(size_bytes, int) and len(payload) != size_bytes:
            failures.append(f"artifact[{index}] size mismatch for {key}: {len(payload)} != {size_bytes}")
        actual_sha = hashlib.sha256(payload).hexdigest()
        if sha256 and actual_sha != sha256:
            failures.append(f"artifact[{index}] sha256 mismatch for {key}: {actual_sha} != {sha256}")
    return failures


def main() -> None:
    args = parse_args()
    storage_dir = Path(args.storage_dir)
    state_path = Path(args.state_path) if args.state_path else storage_dir / "state.json"
    state = load_state_json(state_path)

    local_result = validate_local_raw_hh(
        storage_dir,
        state,
        min_rows=args.min_rows,
        max_removed_share=args.max_removed_share,
        require_date_semantics=args.require_date_semantics,
        date_window_from=args.date_window_from,
        date_window_to=args.date_window_to,
        max_date_unknown_share=args.max_date_unknown_share,
        max_date_out_of_window_share=args.max_date_out_of_window_share,
        min_critical_field_completeness=args.min_critical_field_completeness,
        max_zero_row_shards=args.max_zero_row_shards,
        max_collection_error_share=args.max_collection_error_share,
        min_collection_success_share=args.min_collection_success_share,
    )
    result = {
        "status": local_result["status"],
        "storage_dir": str(storage_dir),
        "run_id": state.get("last_run_id"),
        "local": local_result,
    }

    if args.require_s3:
        bucket = args.bucket or os.environ.get("S3_BUCKET_RAW_HH")
        if not bucket:
            raise SystemExit("S3 bucket not provided. Set S3_BUCKET_RAW_HH or pass --bucket.")
        client = create_s3_client(os.environ)
        result["s3"] = validate_s3_raw_hh(client, bucket, storage_dir, state)
        if result["s3"].get("status") == "failed":
            result["status"] = "failed"

    if args.report_path:
        write_json_atomic(Path(args.report_path), result)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    failures = list(local_result["failures"])
    if result.get("s3", {}).get("status") == "failed":
        failures.append("missing S3 raw HH objects")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
