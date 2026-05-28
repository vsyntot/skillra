from __future__ import annotations

from skillra_pda.ingest.source_registry import (
    SOURCE_REGISTRY_SCHEMA_VERSION,
    build_source_capability_ref,
    registry_payload,
    registry_sha256,
    validate_source_capability_ref,
)


def test_source_registry_exposes_required_governance_fields() -> None:
    registry = registry_payload()

    assert registry["schema_version"] == SOURCE_REGISTRY_SCHEMA_VERSION
    hh = next(source for source in registry["sources"] if source["source_id"] == "hh_html")
    assert hh["legal_access_status"]
    assert hh["collection_mode"] == "html_scrape"
    assert hh["rate_limits"]["min_delay_sec"] >= 1.5
    assert hh["date_semantics"]["publication_date_field"] == "published_at_iso"
    assert "vacancy_id" in hh["supported_fields"]["required"]
    assert hh["coverage"]["dataset_scopes"] == ["all_vacancies", "salary_disclosed"]
    assert hh["cost"]["model"]
    assert hh["risk"]["level"] == "high"

    hh_api = next(source for source in registry["sources"] if source["source_id"] == "hh_api")
    assert hh_api["collection_mode"] == "official_api"
    assert hh_api["date_semantics"]["supports_publication_window_filter"] is True
    assert hh_api["capabilities"][1]["use_case"] == "historical_collection"
    assert hh_api["capabilities"][1]["requires_report"] is True


def test_source_capability_ref_validates_against_registry() -> None:
    ref = build_source_capability_ref(
        source_mode="hh_html",
        use_case="historical_collection",
        capability_status="supported",
        evidence_type="capability_report",
        capability_report_path="reports/source_capability/hh.json",
        requested_date_from="2025-12-01",
        requested_date_to="2025-12-09",
        dataset_scope="all_vacancies",
        salary_only=False,
        areas=[113],
    )

    assert ref["registry_sha256"] == registry_sha256()
    assert (
        validate_source_capability_ref(
            ref,
            expected_source_mode="hh_html",
            expected_use_case="historical_collection",
            expected_dataset_scope="all_vacancies",
            expected_salary_only=False,
            expected_areas=[113],
            require_supported=True,
        )
        == []
    )


def test_source_capability_ref_rejects_unsupported_status() -> None:
    ref = build_source_capability_ref(
        source_mode="hh_html",
        use_case="historical_collection",
        capability_status="unsupported",
        evidence_type="capability_report",
        capability_report_path="reports/source_capability/hh.json",
    )

    failures = validate_source_capability_ref(ref, expected_use_case="historical_collection", require_supported=True)

    assert any("capability_status" in failure for failure in failures)


def test_source_capability_ref_carries_coverage_contract() -> None:
    ref = build_source_capability_ref(
        source_mode="fixture",
        use_case="historical_collection",
        capability_status="supported",
        evidence_type="test_fixture",
        coverage_claim="test_fixture_only",
        coverage_limitations=["not production evidence"],
        closed_archived_coverage="test_fixture",
    )

    assert ref["coverage_claim"] == "test_fixture_only"
    assert ref["coverage_limitations"] == ["not production evidence"]
    assert ref["closed_archived_coverage"] == "test_fixture"


def test_hh_api_source_capability_ref_can_validate_with_evidence() -> None:
    ref = build_source_capability_ref(
        source_mode="hh_api",
        use_case="historical_collection",
        capability_status="supported",
        evidence_type="capability_report",
        capability_report_path="reports/source_capability/hh_api.json",
        requested_date_from="2025-12-01",
        requested_date_to="2025-12-07",
        dataset_scope="all_vacancies",
        salary_only=False,
        areas=[113],
    )

    assert (
        validate_source_capability_ref(
            ref,
            expected_source_mode="hh_api",
            expected_use_case="historical_collection",
            expected_dataset_scope="all_vacancies",
            expected_salary_only=False,
            expected_areas=[113],
            require_supported=True,
        )
        == []
    )
