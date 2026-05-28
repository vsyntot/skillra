"""Data-product release smoke for Skillra local/prod contours.

This smoke focuses on the release contract around the active dataset:

* API health and active dataset pointer agree;
* search publish status agrees with the served dataset;
* vacancy search returns documents from the same dataset run;
* trend endpoints are blocked unless the dataset is explicitly trend-eligible.

It does not collect data and does not mutate MinIO, Postgres or MeiliSearch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from requests import Response, Session

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.s3_sync_processed import validate_processed_pointer  # noqa: E402
from skillra_pda.storage.s3_client import create_s3_client, download_bytes  # noqa: E402

SERVICE_TOKEN_HEADER = "X-Skillra-Token"
ADMIN_TOKEN_HEADER = "X-Admin-Token"
DEFAULT_BASE_URL = os.environ.get("SKILLRA_API_BASE_URL", "http://localhost:8000").rstrip("/")
DEFAULT_SERVICE_TOKEN = os.environ.get("SKILLRA_API_TOKEN")
DEFAULT_ADMIN_TOKEN = os.environ.get("SKILLRA_ADMIN_TOKEN")
DEFAULT_BASIC_AUTH_USER = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_USER") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_USER"
)
DEFAULT_BASIC_AUTH_PASSWORD = os.environ.get("SKILLRA_SMOKE_BASIC_AUTH_PASSWORD") or os.environ.get(
    "CADDY_ADMIN_BASIC_AUTH_PASSWORD"
)
DEFAULT_REPORT_PATH = Path(__file__).resolve().parent.parent / "reports" / "smoke" / "data_product_release.json"
DEFAULT_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("SKILLRA_SMOKE_REQUEST_TIMEOUT_SECONDS", "240"))
DEFAULT_REQUIRE_PROCESSED_S3 = os.environ.get("SKILLRA_SMOKE_REQUIRE_PROCESSED_S3") == "1"
DEFAULT_PROCESSED_BUCKET = os.environ.get("S3_BUCKET_PROCESSED")


class DataProductSmokeFailure(RuntimeError):
    """Raised when a data-product release smoke check fails."""


class TimeoutSession(Session):
    """Requests session with bounded calls so release smoke cannot hang forever."""

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS)
        return super().request(method, url, **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Skillra data-product release smoke checks")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=DEFAULT_SERVICE_TOKEN)
    parser.add_argument("--admin-token", default=DEFAULT_ADMIN_TOKEN)
    parser.add_argument("--basic-auth-user", default=DEFAULT_BASIC_AUTH_USER)
    parser.add_argument("--basic-auth-password", default=DEFAULT_BASIC_AUTH_PASSWORD)
    parser.add_argument("--search-query", default=os.environ.get("SKILLRA_SMOKE_SEARCH_QUERY", "data"))
    parser.add_argument("--trend-role", default=os.environ.get("SKILLRA_SMOKE_TREND_ROLE", "data"))
    parser.add_argument("--trend-grade", default=os.environ.get("SKILLRA_SMOKE_TREND_GRADE", "middle"))
    parser.add_argument("--trend-skill", default=os.environ.get("SKILLRA_SMOKE_TREND_SKILL", "python"))
    parser.add_argument("--expected-run-id", default=os.environ.get("SKILLRA_EXPECTED_DATASET_RUN_ID"))
    parser.add_argument("--expected-runtime-env", default=os.environ.get("SKILLRA_EXPECTED_RUNTIME_ENV"))
    parser.add_argument("--expected-public-base-url", default=os.environ.get("SKILLRA_EXPECTED_PUBLIC_BASE_URL"))
    parser.add_argument("--require-processed-s3", action="store_true", default=DEFAULT_REQUIRE_PROCESSED_S3)
    parser.add_argument("--processed-bucket", default=DEFAULT_PROCESSED_BUCKET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def _print_step(message: str) -> None:
    print(f"[data-product-smoke] {message}", flush=True)


def _check_response(response: Response, context: str) -> Any:
    if not response.ok:
        detail = response.text.strip()
        suffix = f" - {detail}" if detail else ""
        raise DataProductSmokeFailure(f"{context} failed: HTTP {response.status_code} {response.reason}{suffix}")
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.content


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataProductSmokeFailure(message)


def _string_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _trend_expected_ready(dataset_meta: dict[str, Any]) -> bool:
    product_eligibility = dataset_meta.get("product_eligibility")
    if not isinstance(product_eligibility, dict):
        return False
    trends = product_eligibility.get("trends")
    return bool(isinstance(trends, dict) and trends.get("eligible") is True)


def _validate_health(
    health: dict[str, Any],
    *,
    expected_run_id: str | None = None,
    expected_runtime_env: str | None = None,
    expected_public_base_url: str | None = None,
) -> str:
    _require(health.get("status") == "ok", f"/v1/health status is not ok: {health.get('status')}")
    _require(health.get("database") == "ok", f"database is not ok: {health.get('database')}")
    _require(health.get("redis") in {"ok", "not_configured"}, f"redis is not ok: {health.get('redis')}")
    _require(
        health.get("meilisearch") in {"ok", "not_configured"},
        f"meilisearch is not ok: {health.get('meilisearch')}",
    )
    _require(health.get("datastore_status") == "ok", f"datastore is not ok: {health.get('datastore_status')}")
    _require(health.get("data_consistency") == "ok", f"data consistency is not ok: {health.get('data_consistency')}")

    if expected_runtime_env:
        actual_runtime_env = _string_or_none(health.get("runtime_env"))
        expected_normalized = expected_runtime_env.strip().lower()
        _require(
            actual_runtime_env == expected_normalized,
            f"/v1/health runtime_env {actual_runtime_env} != expected {expected_normalized}",
        )

    if expected_public_base_url:
        actual_public_base_url = _string_or_none(health.get("public_base_url"))
        expected_public_base_url = expected_public_base_url.strip().rstrip("/")
        _require(
            actual_public_base_url == expected_public_base_url,
            f"/v1/health public_base_url {actual_public_base_url} != expected {expected_public_base_url}",
        )

    dataset_run_id = _string_or_none(health.get("dataset_run_id"))
    _require(dataset_run_id is not None, "/v1/health missing dataset_run_id")
    if expected_run_id:
        _require(
            dataset_run_id == expected_run_id,
            f"/v1/health dataset_run_id {dataset_run_id} != expected {expected_run_id}",
        )

    data_run = health.get("data_run")
    _require(isinstance(data_run, dict), "/v1/health missing data_run")
    active = data_run.get("active")
    _require(isinstance(active, dict), "/v1/health missing active dataset pointer")
    _require(active.get("run_id") == dataset_run_id, "active dataset run does not match served dataset run")
    _require(active.get("state") == "published", f"active dataset is not published: {active.get('state')}")

    search_publish = health.get("search_publish")
    _require(isinstance(search_publish, dict), "/v1/health missing search_publish")
    _require(search_publish.get("status") == "ok", f"search_publish is not ok: {search_publish.get('status')}")
    _require(
        search_publish.get("dataset_run_id") == dataset_run_id,
        "search_publish dataset_run_id does not match served dataset_run_id",
    )
    _require(int(search_publish.get("indexed") or 0) > 0, "search_publish indexed count must be positive")
    return dataset_run_id


def _validate_dataset_meta(dataset_meta: dict[str, Any], dataset_run_id: str) -> dict[str, Any]:
    meta_run_id = _string_or_none(dataset_meta.get("run_id"))
    if meta_run_id is not None:
        _require(meta_run_id == dataset_run_id, "dataset meta run_id does not match health dataset_run_id")

    quality_gates = dataset_meta.get("quality_gates")
    if isinstance(quality_gates, dict):
        _require(
            quality_gates.get("status") == "passed",
            f"dataset quality gates are not passed: {quality_gates.get('status')}",
        )

    rows = dataset_meta.get("features_rows") or dataset_meta.get("vacancy_count")
    if rows is not None:
        _require(int(rows) > 0, "dataset row count must be positive")

    product_eligibility = dataset_meta.get("product_eligibility")
    if product_eligibility is not None:
        _require(isinstance(product_eligibility, dict), "product_eligibility must be an object")

    return {
        "run_id": meta_run_id or dataset_run_id,
        "features_rows": rows,
        "quality_status": quality_gates.get("status") if isinstance(quality_gates, dict) else None,
        "trend_ready": _trend_expected_ready(dataset_meta),
        "dataset_semantic_type": dataset_meta.get("dataset_semantic_type"),
        "date_semantics_status": dataset_meta.get("date_semantics_status"),
    }


def _validate_indexer_status(indexer_status: dict[str, Any], dataset_run_id: str) -> dict[str, Any]:
    _require(indexer_status.get("status") in {"ok", "success"}, f"unexpected indexer status: {indexer_status}")
    _require(
        indexer_status.get("dataset_run_id") == dataset_run_id,
        "indexer status dataset_run_id does not match served dataset_run_id",
    )
    for field in ("served_dataset_run_id", "active_dataset_run_id"):
        value = indexer_status.get(field)
        if value is not None:
            _require(value == dataset_run_id, f"indexer status {field} does not match served dataset_run_id")
    _require(int(indexer_status.get("indexed") or 0) > 0, "indexer indexed count must be positive")
    return {
        "status": indexer_status.get("status"),
        "dataset_run_id": indexer_status.get("dataset_run_id"),
        "indexed": indexer_status.get("indexed"),
    }


def _validate_search(search_payload: dict[str, Any], dataset_run_id: str) -> dict[str, Any]:
    results = search_payload.get("results")
    _require(isinstance(results, list), "search response missing results list")
    _require(len(results) > 0, "search returned no results")
    _require(search_payload.get("dataset_run_id") == dataset_run_id, "search dataset_run_id mismatch")
    index_dataset_run_id = search_payload.get("index_dataset_run_id")
    if index_dataset_run_id is not None:
        _require(index_dataset_run_id == dataset_run_id, "search index_dataset_run_id mismatch")
    warnings = search_payload.get("warnings")
    if isinstance(warnings, list):
        stale = [warning for warning in warnings if "differs from API dataset run" in str(warning)]
        _require(not stale, f"search reports stale index warnings: {stale}")
    mismatched_results = [
        result.get("dataset_run_id")
        for result in results
        if isinstance(result, dict) and result.get("dataset_run_id") not in {None, dataset_run_id}
    ]
    _require(not mismatched_results, f"search result dataset_run_id mismatch: {mismatched_results[:3]}")
    return {
        "results": len(results),
        "dataset_run_id": search_payload.get("dataset_run_id"),
        "index_dataset_run_id": search_payload.get("index_dataset_run_id"),
        "warnings": warnings or [],
    }


def _validate_trend(payload: dict[str, Any], *, expected_ready: bool, name: str) -> dict[str, Any]:
    claim_status = payload.get("claim_status")
    data = payload.get("data")
    _require(isinstance(data, list), f"{name} trend response missing data list")
    if expected_ready:
        _require(claim_status == "ready", f"{name} trend must be ready for trend-eligible dataset")
    else:
        _require(claim_status == "blocked", f"{name} trend must be blocked for non-trend-eligible dataset")
        _require(data == [], f"{name} trend must return empty data when blocked")
    return {"claim_status": claim_status, "points": len(data), "warnings": payload.get("warnings") or []}


def _load_s3_json(client: Any, bucket: str, key: str) -> dict[str, Any]:
    payload = json.loads(download_bytes(client, bucket, key).decode("utf-8"))
    _require(isinstance(payload, dict), f"s3://{bucket}/{key} must contain a JSON object")
    return payload


def _validate_processed_s3(bucket: str, dataset_run_id: str) -> dict[str, Any]:
    client = create_s3_client(os.environ)
    latest_pointer = _load_s3_json(client, bucket, "latest_pointer.json")
    _require(
        latest_pointer.get("run_id") == dataset_run_id,
        f"processed latest_pointer run_id {latest_pointer.get('run_id')} != active dataset_run_id {dataset_run_id}",
    )
    pointer_failures = validate_processed_pointer(client, bucket, latest_pointer)
    _require(not pointer_failures, "processed latest pointer validation failed: " + "; ".join(pointer_failures))

    active_pointer = _load_s3_json(client, bucket, "hh/published/active_dataset.json")
    _require(
        active_pointer.get("run_id") == dataset_run_id,
        f"processed active_dataset run_id {active_pointer.get('run_id')} != active dataset_run_id {dataset_run_id}",
    )
    active_latest_pointer = active_pointer.get("latest_pointer")
    _require(isinstance(active_latest_pointer, dict), "processed active_dataset latest_pointer must be an object")
    _require(
        active_latest_pointer.get("run_id") == dataset_run_id,
        "processed active_dataset latest_pointer run_id does not match active dataset_run_id",
    )
    return {
        "bucket": bucket,
        "latest_pointer_run_id": latest_pointer.get("run_id"),
        "active_dataset_run_id": active_pointer.get("run_id"),
        "artifacts": len(latest_pointer.get("artifacts") or []),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def run_smoke(
    *,
    base_url: str,
    token: str,
    admin_token: str | None,
    basic_auth_user: str | None,
    basic_auth_password: str | None,
    search_query: str,
    trend_role: str,
    trend_grade: str,
    trend_skill: str,
    expected_run_id: str | None,
    expected_runtime_env: str | None,
    expected_public_base_url: str | None,
    require_processed_s3: bool,
    processed_bucket: str | None,
    report_path: Path,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    _print_step(f"Target API base: {base_url}")

    with TimeoutSession() as session:
        session.headers.update({SERVICE_TOKEN_HEADER: token})
        if basic_auth_user and basic_auth_password:
            session.auth = (basic_auth_user, basic_auth_password)

        _print_step("Checking /v1/health")
        health = _check_response(session.get(f"{base_url}/v1/health"), "/v1/health")
        dataset_run_id = _validate_health(
            health,
            expected_run_id=expected_run_id,
            expected_runtime_env=expected_runtime_env,
            expected_public_base_url=expected_public_base_url,
        )

        _print_step("Checking /v1/meta/dataset")
        dataset_meta = _check_response(session.get(f"{base_url}/v1/meta/dataset"), "/v1/meta/dataset")
        meta_summary = _validate_dataset_meta(dataset_meta, dataset_run_id)

        indexer_summary = None
        if admin_token:
            _print_step("Checking /v1/admin/indexer-status")
            response = session.get(f"{base_url}/v1/admin/indexer-status", headers={ADMIN_TOKEN_HEADER: admin_token})
            indexer_status = _check_response(response, "/v1/admin/indexer-status")
            indexer_summary = _validate_indexer_status(indexer_status, dataset_run_id)

        _print_step("Checking /v1/search/vacancies dataset contract")
        search_payload = _check_response(
            session.get(f"{base_url}/v1/search/vacancies", params={"q": search_query, "limit": 5}),
            "/v1/search/vacancies",
        )
        search_summary = _validate_search(search_payload, dataset_run_id)

        expected_trend_ready = bool(meta_summary["trend_ready"])
        _print_step("Checking trend claim contract")
        trend_summaries = {
            "salary": _validate_trend(
                _check_response(
                    session.get(
                        f"{base_url}/v1/market/trends/salary",
                        params={"role": trend_role, "grade": trend_grade, "weeks": 12},
                    ),
                    "/v1/market/trends/salary",
                ),
                expected_ready=expected_trend_ready,
                name="salary",
            ),
            "vacancy_count": _validate_trend(
                _check_response(
                    session.get(
                        f"{base_url}/v1/market/trends/vacancy-count",
                        params={"role": trend_role, "grade": trend_grade, "weeks": 12},
                    ),
                    "/v1/market/trends/vacancy-count",
                ),
                expected_ready=expected_trend_ready,
                name="vacancy-count",
            ),
            "skill_demand": _validate_trend(
                _check_response(
                    session.get(
                        f"{base_url}/v1/market/trends/skill-demand",
                        params={"skill": trend_skill, "role": trend_role, "grade": trend_grade, "weeks": 12},
                    ),
                    "/v1/market/trends/skill-demand",
                ),
                expected_ready=expected_trend_ready,
                name="skill-demand",
            ),
        }

    processed_s3_summary = None
    if require_processed_s3:
        if not processed_bucket:
            raise DataProductSmokeFailure(
                "Processed S3 validation is required but S3_BUCKET_PROCESSED/--processed-bucket is empty."
            )
        _print_step("Checking processed MinIO/S3 latest and active pointers")
        processed_s3_summary = _validate_processed_s3(processed_bucket, dataset_run_id)

    report = {
        "status": "ok",
        "base_url": base_url,
        "runtime_env": health.get("runtime_env"),
        "public_base_url": health.get("public_base_url"),
        "dataset_run_id": dataset_run_id,
        "dataset_meta": meta_summary,
        "processed_s3": processed_s3_summary,
        "indexer_status": indexer_summary,
        "search": search_summary,
        "trends": trend_summaries,
    }
    _write_report(report_path, report)
    _print_step(f"SUCCESS: data-product release smoke passed, report at {report_path}")
    return report


def main() -> None:
    args = parse_args()
    if not args.token:
        raise DataProductSmokeFailure("Service token is required. Provide --token or set SKILLRA_API_TOKEN.")

    try:
        run_smoke(
            base_url=args.base_url,
            token=args.token,
            admin_token=args.admin_token,
            basic_auth_user=args.basic_auth_user,
            basic_auth_password=args.basic_auth_password,
            search_query=args.search_query,
            trend_role=args.trend_role,
            trend_grade=args.trend_grade,
            trend_skill=args.trend_skill,
            expected_run_id=args.expected_run_id,
            expected_runtime_env=args.expected_runtime_env,
            expected_public_base_url=args.expected_public_base_url,
            require_processed_s3=args.require_processed_s3,
            processed_bucket=args.processed_bucket,
            report_path=args.report,
        )
    except DataProductSmokeFailure as exc:
        sys.stderr.write(f"[data-product-smoke] FAILED: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
