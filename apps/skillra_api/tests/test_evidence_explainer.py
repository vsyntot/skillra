from __future__ import annotations

from skillra_api.schemas import (
    MarketSummary,
    PersonaAnalysisResponse,
    ProfileQualityOut,
    SkillGapEntry,
    UserProfileOut,
)
from skillra_api.services.evidence_explainer import build_deterministic_explainer, build_evidence_packet


def test_skill_gap_explainer_uses_only_packet_evidence_refs() -> None:
    packet = build_evidence_packet(
        telegram_user_id=101,
        profile=_profile(),
        profile_quality=_profile_quality(),
        analysis=_analysis(product_eligibility=_eligible_all()),
    )

    output = build_deterministic_explainer(packet)

    packet_ids = {item.evidence_id for item in packet.evidence}
    assert output.status == "answered"
    assert output.evidence_refs
    assert {ref.evidence_id for ref in output.evidence_refs}.issubset(packet_ids)
    assert "гарант" not in output.answer.lower()


def test_weak_dataset_blocks_historical_and_strong_recommendation_claims() -> None:
    packet = build_evidence_packet(
        telegram_user_id=102,
        profile=_profile(),
        profile_quality=_profile_quality(),
        analysis=_analysis(
            product_eligibility={
                "search": {"eligible": True},
                "salary": {"eligible": False},
                "trends": {"eligible": False},
                "recommendations": {"eligible": False},
            },
            date_semantics_status="current_snapshot_only",
        ),
        task="market_change_summary",
    )

    output = build_deterministic_explainer(packet)

    assert "historical_trend_claims" in packet.output_constraints.blocked_claims
    assert "salary_claims" in packet.output_constraints.blocked_claims
    assert "strong_recommendation_claims" in packet.output_constraints.blocked_claims
    assert output.status == "blocked"
    assert "нет подтвержденной исторической динамики" in output.answer


def test_degraded_search_blocks_strong_vacancy_fit_claims() -> None:
    packet = build_evidence_packet(
        telegram_user_id=103,
        profile=_profile(),
        profile_quality=_profile_quality(),
        analysis=_analysis(product_eligibility=_eligible_all()),
        task="vacancy_fit_explanation",
        search_state="degraded",
        index_status="degraded",
        degraded_reason="MeiliSearch health check is degraded.",
    )

    output = build_deterministic_explainer(packet)

    assert "strong_vacancy_fit_claims" in packet.output_constraints.blocked_claims
    assert any(item.evidence_id == "search:runtime_state" for item in packet.evidence)
    assert output.status == "fallback"
    assert "fit" in output.answer


def _profile() -> UserProfileOut:
    return UserProfileOut(
        telegram_user_id=101,
        username="test-user",
        target_role="data",
        target_grade="junior",
        target_city_tier="Moscow",
        target_country="Russia",
        target_region="Moscow",
        target_city="Moscow",
        target_geo_scope="remote",
        target_work_mode="remote",
        target_domain="analytics",
        current_skills=[],
        warnings=[],
    )


def _profile_quality() -> ProfileQualityOut:
    return ProfileQualityOut(
        score=100,
        is_complete=True,
        completed_fields=[
            "target_role",
            "target_grade",
            "target_geo",
            "target_work_mode",
            "target_domain",
            "current_skills",
        ],
        missing_fields=[],
    )


def _analysis(
    *,
    product_eligibility: dict[str, object],
    date_semantics_status: str = "passed",
) -> PersonaAnalysisResponse:
    trust = {
        "dataset_run_id": "run-038",
        "generated_at_utc": "2026-05-27T00:00:00+00:00",
        "freshness": "fresh",
        "sample_size": 100,
        "confidence": "high",
        "source_kind": "current_market_snapshot",
        "dataset_semantic_type": "current_market_view",
        "date_semantics_status": date_semantics_status,
        "product_eligibility": product_eligibility,
    }
    return PersonaAnalysisResponse(
        **trust,
        market_summary=MarketSummary(
            **trust,
            vacancy_count=100,
            salary_sample_size=20,
            salary_coverage_share=0.2,
            min_market_n=80,
            top_skills=["python", "sql"],
        ),
        recommended_skills=["python"],
        top_skill_demand=[
            SkillGapEntry(skill_name="python", market_share=0.62, persona_has=False, gap=True),
            SkillGapEntry(skill_name="sql", market_share=0.51, persona_has=True, gap=False),
        ],
        skill_gap=[
            SkillGapEntry(skill_name="python", market_share=0.62, persona_has=False, gap=True),
            SkillGapEntry(skill_name="sql", market_share=0.51, persona_has=True, gap=False),
        ],
        warnings=[],
        filters_used={"role": "data", "grade": "junior"},
    )


def _eligible_all() -> dict[str, object]:
    return {
        "search": {"eligible": True},
        "salary": {"eligible": True},
        "trends": {"eligible": True},
        "recommendations": {"eligible": True},
    }
