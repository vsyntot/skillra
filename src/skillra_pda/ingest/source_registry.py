from __future__ import annotations

"""Versioned source capability registry for Skillra vacancy collection."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

SOURCE_REGISTRY_SCHEMA_VERSION = 1

TREND_READY_GATE_VERSION = "2026-05-27.v1"
TREND_BLOCKED_USER_MESSAGE = (
    "Историческая динамика сейчас заблокирована: нужен trend-ready датасет с подтвержденными датами публикации, "
    "достаточным числом периодов, покрытием сегментов и проверенным source capability."
)

SOURCE_REGISTRY: dict[str, Any] = {
    "schema_version": SOURCE_REGISTRY_SCHEMA_VERSION,
    "sources": [
        {
            "source_id": "hh_html",
            "source_mode": "hh_html",
            "display_name": "HH.ru HTML search",
            "legal_access_status": "internal_current_snapshot_allowed_historical_requires_review",
            "collection_mode": "html_scrape",
            "prod_allowed": True,
            "rate_limits": {
                "min_delay_sec": 1.5,
                "max_pages_per_run": None,
                "retry_backoff_sec": 300,
                "max_attempts_per_day": 1,
            },
            "date_semantics": {
                "publication_date_field": "published_at_iso",
                "supports_publication_window_filter": True,
                "historical_collection": "requires_capability_report",
            },
            "supported_fields": {
                "required": ["vacancy_id", "title", "vacancy_url", "published_at_iso"],
                "optional": ["salary_from", "salary_to", "skills", "employer", "schedule", "experience"],
            },
            "coverage": {
                "areas": [113],
                "dataset_scopes": ["all_vacancies", "salary_disclosed"],
                "notes": "Coverage depends on HH search result availability and anti-abuse limits.",
            },
            "cost": {
                "model": "free_source_operational_cost",
                "notes": "No paid contract; operational scraping cost only.",
            },
            "risk": {
                "level": "high",
                "notes": "HTML drift, access limits and historical date semantics must be proven per requested window.",
            },
            "capabilities": [
                {
                    "capability_id": "hh_html.current_snapshot.v1",
                    "use_case": "current_snapshot",
                    "status": "supported",
                    "requires_report": False,
                    "requires_date_semantics": False,
                    "allowed_dataset_semantic_types": ["current_market_snapshot"],
                },
                {
                    "capability_id": "hh_html.historical_publication_window.v1",
                    "use_case": "historical_collection",
                    "status": "requires_evidence",
                    "requires_report": True,
                    "requires_date_semantics": True,
                    "allowed_dataset_semantic_types": ["historical_publication_facts"],
                },
            ],
        },
        {
            "source_id": "hh_api",
            "source_mode": "hh_api",
            "display_name": "HH.ru official API vacancy search",
            "legal_access_status": "official_api_access_required",
            "collection_mode": "official_api",
            "prod_allowed": True,
            "rate_limits": {
                "min_delay_sec": 1.0,
                "max_pages_per_run": None,
                "retry_backoff_sec": 300,
                "max_attempts_per_day": 1,
            },
            "date_semantics": {
                "publication_date_field": "published_at_iso",
                "supports_publication_window_filter": True,
                "historical_collection": "requires_capability_report",
                "notes": (
                    "HH OpenAPI exposes date_from/date_to and published_at, "
                    "but access and history depth must be proven."
                ),
            },
            "supported_fields": {
                "required": ["vacancy_id", "title", "vacancy_url", "published_at_iso"],
                "optional": [
                    "salary_from",
                    "salary_to",
                    "company",
                    "city",
                    "schedule",
                    "experience",
                    "employment_type",
                ],
            },
            "coverage": {
                "areas": [113],
                "dataset_scopes": ["all_vacancies", "salary_disclosed"],
                "notes": (
                    "Search result depth is bounded by HH API pagination limits; dense windows must be split "
                    "adaptively before collection."
                ),
            },
            "cost": {
                "model": "official_api_operational_or_contract_cost",
                "notes": "Requires a working HH API access path; public unauthenticated access may hit captcha/403.",
            },
            "risk": {
                "level": "medium",
                "notes": (
                    "Official API is structurally preferable to HTML, but full historical coverage is not assumed "
                    "without source-capability evidence."
                ),
            },
            "capabilities": [
                {
                    "capability_id": "hh_api.current_snapshot.v1",
                    "use_case": "current_snapshot",
                    "status": "requires_evidence",
                    "requires_report": True,
                    "requires_date_semantics": False,
                    "allowed_dataset_semantic_types": ["current_market_snapshot"],
                },
                {
                    "capability_id": "hh_api.historical_publication_window.v1",
                    "use_case": "historical_collection",
                    "status": "requires_evidence",
                    "requires_report": True,
                    "requires_date_semantics": True,
                    "allowed_dataset_semantic_types": ["historical_publication_facts"],
                },
            ],
        },
        {
            "source_id": "fixture",
            "source_mode": "fixture",
            "display_name": "Local fixture CSV",
            "legal_access_status": "test_only",
            "collection_mode": "fixture_copy",
            "prod_allowed": False,
            "rate_limits": {"min_delay_sec": 0.0, "max_pages_per_run": 1, "retry_backoff_sec": 0},
            "date_semantics": {
                "publication_date_field": "published_at_iso",
                "supports_publication_window_filter": True,
                "historical_collection": "test_only",
            },
            "supported_fields": {
                "required": ["vacancy_id", "title", "published_at_iso"],
                "optional": ["vacancy_url", "salary_from", "salary_to", "skills"],
            },
            "coverage": {"areas": [], "dataset_scopes": ["all_vacancies", "salary_disclosed"]},
            "cost": {"model": "none", "notes": "Deterministic CI/test fixture."},
            "risk": {"level": "low", "notes": "Not a production data source."},
            "capabilities": [
                {
                    "capability_id": "fixture.current_snapshot.v1",
                    "use_case": "current_snapshot",
                    "status": "supported",
                    "requires_report": False,
                    "requires_date_semantics": False,
                    "allowed_dataset_semantic_types": ["current_market_snapshot"],
                },
                {
                    "capability_id": "fixture.historical_publication_window.v1",
                    "use_case": "historical_collection",
                    "status": "supported",
                    "requires_report": False,
                    "requires_date_semantics": True,
                    "allowed_dataset_semantic_types": ["historical_publication_facts"],
                },
            ],
        },
    ],
}


class SourceRegistryError(ValueError):
    """Raised when source registry or capability evidence is invalid."""


def registry_payload() -> dict[str, Any]:
    return copy.deepcopy(SOURCE_REGISTRY)


def registry_sha256() -> str:
    payload = json.dumps(SOURCE_REGISTRY, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_by_mode(source_mode: str) -> dict[str, Any]:
    for source in SOURCE_REGISTRY["sources"]:
        if source.get("source_mode") == source_mode or source.get("source_id") == source_mode:
            return copy.deepcopy(source)
    raise SourceRegistryError(f"Unknown source mode: {source_mode!r}")


def capability_for(source_mode: str, use_case: str) -> dict[str, Any]:
    source = source_by_mode(source_mode)
    for capability in source.get("capabilities") or []:
        if capability.get("use_case") == use_case:
            return copy.deepcopy(capability)
    raise SourceRegistryError(f"Source {source_mode!r} has no capability for use_case {use_case!r}")


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_capability_ref(
    *,
    source_mode: str,
    use_case: str,
    capability_status: str | None = None,
    evidence_type: str | None = None,
    capability_report_path: Path | str | None = None,
    requested_date_from: str | None = None,
    requested_date_to: str | None = None,
    dataset_scope: str | None = None,
    salary_only: bool | None = None,
    areas: list[int] | tuple[int, ...] | None = None,
    coverage_claim: str | None = None,
    coverage_limitations: list[str] | tuple[str, ...] | None = None,
    closed_archived_coverage: str | None = None,
) -> dict[str, Any]:
    source = source_by_mode(source_mode)
    capability = capability_for(source_mode, use_case)
    report_path = Path(capability_report_path) if capability_report_path is not None else None
    ref: dict[str, Any] = {
        "registry_schema_version": SOURCE_REGISTRY_SCHEMA_VERSION,
        "registry_sha256": registry_sha256(),
        "source_id": source["source_id"],
        "source_mode": source["source_mode"],
        "capability_id": capability["capability_id"],
        "use_case": use_case,
        "capability_status": capability_status or capability["status"],
        "evidence_type": evidence_type or ("capability_report" if capability.get("requires_report") else "registry"),
        "requires_report": bool(capability.get("requires_report")),
        "requires_date_semantics": bool(capability.get("requires_date_semantics")),
        "allowed_dataset_semantic_types": list(capability.get("allowed_dataset_semantic_types") or []),
    }
    if report_path is not None:
        ref["capability_report_path"] = str(report_path)
        if report_path.exists():
            ref["capability_report_sha256"] = compute_file_sha256(report_path)
    if requested_date_from is not None:
        ref["requested_date_from"] = requested_date_from
    if requested_date_to is not None:
        ref["requested_date_to"] = requested_date_to
    if dataset_scope is not None:
        ref["dataset_scope"] = dataset_scope
    if salary_only is not None:
        ref["salary_only"] = bool(salary_only)
    if areas is not None:
        ref["areas"] = [int(area) for area in areas]
    if coverage_claim is not None:
        ref["coverage_claim"] = coverage_claim
    if coverage_limitations is not None:
        ref["coverage_limitations"] = [str(item) for item in coverage_limitations]
    if closed_archived_coverage is not None:
        ref["closed_archived_coverage"] = closed_archived_coverage
    return ref


def validate_source_capability_ref(
    ref: object,
    *,
    expected_source_mode: str | None = None,
    expected_use_case: str | None = None,
    expected_dataset_scope: str | None = None,
    expected_salary_only: bool | None = None,
    expected_areas: tuple[int, ...] | list[int] | None = None,
    require_supported: bool = False,
) -> list[str]:
    failures: list[str] = []
    if not isinstance(ref, dict):
        return ["source_capability_ref must be an object"]
    if ref.get("registry_schema_version") != SOURCE_REGISTRY_SCHEMA_VERSION:
        failures.append(
            f"registry_schema_version is {ref.get('registry_schema_version')!r}, "
            f"expected {SOURCE_REGISTRY_SCHEMA_VERSION}"
        )
    if ref.get("registry_sha256") != registry_sha256():
        failures.append("registry_sha256 does not match current source registry")
    source_mode = str(ref.get("source_mode") or "")
    try:
        capability = capability_for(source_mode, str(ref.get("use_case") or expected_use_case or ""))
    except SourceRegistryError as exc:
        failures.append(str(exc))
        capability = {}
    if expected_source_mode and source_mode != expected_source_mode:
        failures.append(f"source_mode is {source_mode!r}, expected {expected_source_mode!r}")
    if expected_use_case and ref.get("use_case") != expected_use_case:
        failures.append(f"use_case is {ref.get('use_case')!r}, expected {expected_use_case!r}")
    if capability and ref.get("capability_id") != capability.get("capability_id"):
        failures.append(f"capability_id is {ref.get('capability_id')!r}, expected {capability.get('capability_id')!r}")
    if require_supported and ref.get("capability_status") != "supported":
        failures.append(f"capability_status is {ref.get('capability_status')!r}, expected 'supported'")
    if expected_dataset_scope is not None and ref.get("dataset_scope") != expected_dataset_scope:
        failures.append(f"dataset_scope is {ref.get('dataset_scope')!r}, expected {expected_dataset_scope!r}")
    if expected_salary_only is not None and bool(ref.get("salary_only")) != bool(expected_salary_only):
        failures.append(f"salary_only is {bool(ref.get('salary_only'))!r}, expected {bool(expected_salary_only)!r}")
    if expected_areas is not None:
        ref_areas = {int(area) for area in ref.get("areas") or []}
        missing = sorted(set(int(area) for area in expected_areas) - ref_areas)
        if missing:
            failures.append("areas do not cover expected areas: " + ", ".join(str(area) for area in missing))
    if capability.get("requires_report") and not ref.get("capability_report_path"):
        failures.append("capability_report_path is required for this capability")
    return failures


def source_capability_ref_from_report(
    report: dict[str, Any], *, report_path: Path | str | None = None
) -> dict[str, Any]:
    ref = report.get("source_capability_ref")
    if isinstance(ref, dict):
        resolved = copy.deepcopy(ref)
        if report_path is not None:
            candidate = Path(report_path)
            resolved.setdefault("capability_report_path", str(candidate))
            if candidate.exists():
                resolved["capability_report_sha256"] = compute_file_sha256(candidate)
        return resolved
    return build_source_capability_ref(
        source_mode=str(report.get("source_mode") or ""),
        use_case="historical_collection",
        capability_status=str(report.get("capability_status") or ""),
        evidence_type="capability_report",
        capability_report_path=report_path,
        requested_date_from=report.get("requested_date_from"),
        requested_date_to=report.get("requested_date_to"),
        dataset_scope=report.get("dataset_scope"),
        salary_only=bool(report.get("salary_only")) if report.get("salary_only") is not None else None,
        areas=report.get("areas") or [],
        coverage_claim=report.get("coverage_claim"),
        coverage_limitations=report.get("coverage_limitations") or [],
        closed_archived_coverage=report.get("closed_archived_coverage"),
    )
