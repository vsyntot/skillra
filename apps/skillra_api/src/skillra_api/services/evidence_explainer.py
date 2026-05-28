from __future__ import annotations

import re
from typing import Any

from skillra_api.schemas import (
    CareerPlanOut,
    EvidenceDatasetContext,
    EvidenceExplainerOut,
    EvidenceExplainerStatus,
    EvidenceItem,
    EvidenceOutputConstraints,
    EvidencePacketOut,
    EvidencePlanActionContext,
    EvidencePlanContext,
    EvidenceRefOut,
    EvidenceSearchContext,
    EvidenceSearchState,
    EvidenceSurface,
    EvidenceTask,
    EvidenceUserContext,
    PersonaAnalysisResponse,
    ProfileQualityOut,
    UserProfileOut,
)

EVIDENCE_PACKET_VERSION = "evidence_packet.v1"
EVIDENCE_EXPLAINER_VERSION = "evidence_explainer.v1"
ALLOWED_TASKS: list[EvidenceTask] = [
    "skill_gap_explanation",
    "career_action_draft",
    "vacancy_fit_explanation",
    "market_change_summary",
    "fallback_copy",
]
FORBIDDEN_CLAIMS = [
    "guaranteed_outcomes",
    "unsupported_salary_claims",
    "unsupported_historical_trend_claims",
    "raw_resume_or_pii",
    "provider_or_model_speculation",
]


def build_evidence_packet(
    *,
    telegram_user_id: int,
    profile: UserProfileOut,
    profile_quality: ProfileQualityOut,
    analysis: PersonaAnalysisResponse,
    plan: CareerPlanOut | None = None,
    task: EvidenceTask = "skill_gap_explanation",
    surface: EvidenceSurface = "web",
    search_state: str | None = None,
    index_status: str | None = None,
    degraded_reason: str | None = None,
    search_warnings: list[str] | None = None,
) -> EvidencePacketOut:
    """Build a PII-minimized packet of facts that a bounded explainer may use."""

    dataset = EvidenceDatasetContext(**_dataset_payload(analysis))
    search = EvidenceSearchContext(
        search_state=_normalize_search_state(search_state),
        index_status=index_status,
        degraded_reason=degraded_reason,
        warnings=search_warnings or [],
    )
    plan_context = _plan_context(plan)
    blocked_claims = _blocked_claims(dataset, search)
    evidence = _evidence_items(analysis, dataset, plan_context, search)
    warnings = _packet_warnings(analysis, dataset, search)

    return EvidencePacketOut(
        version=EVIDENCE_PACKET_VERSION,
        task=task,
        surface=surface,
        telegram_user_id=telegram_user_id,
        profile=EvidenceUserContext(
            target_role=profile.target_role,
            target_grade=profile.target_grade,
            target_city_tier=profile.target_city_tier,
            target_country=profile.target_country,
            target_region=profile.target_region,
            target_city=profile.target_city,
            target_geo_scope=profile.target_geo_scope,
            target_work_mode=profile.target_work_mode,
            target_domain=profile.target_domain,
            current_skills=profile.current_skills,
            profile_quality=profile_quality,
        ),
        dataset=dataset,
        market_summary=analysis.market_summary,
        skill_gap=analysis.skill_gap,
        recommended_skills=analysis.recommended_skills,
        plan=plan_context,
        search=search,
        output_constraints=EvidenceOutputConstraints(
            allowed_tasks=ALLOWED_TASKS,
            forbidden_claims=FORBIDDEN_CLAIMS,
            blocked_claims=blocked_claims,
        ),
        evidence=evidence,
        warnings=warnings,
    )


def build_deterministic_explainer(packet: EvidencePacketOut) -> EvidenceExplainerOut:
    """Return bounded Russian copy based only on cited packet facts."""

    refs_by_id = {item.evidence_id: item for item in packet.evidence}
    uncertainties = _uncertainties(packet)
    blocked_claims = packet.output_constraints.blocked_claims

    if packet.task == "fallback_copy":
        return _fallback(
            packet,
            "Пока показываю только проверяемые факты из текущего пакета без дополнительных выводов.",
            refs_by_id=refs_by_id,
            uncertainties=uncertainties,
        )

    if not packet.profile.profile_quality.is_complete:
        return _fallback(
            packet,
            "Профиль еще неполный, поэтому объяснение ограничено заполненными полями и не делает выводов о приоритете.",
            status="blocked",
            refs_by_id=refs_by_id,
            uncertainties=uncertainties,
        )

    if packet.task == "market_change_summary":
        return _fallback(
            packet,
            "В пакете нет подтвержденной исторической динамики, поэтому изменение рынка не формулируется.",
            status="blocked" if "historical_trend_claims" in blocked_claims else "fallback",
            refs_by_id=refs_by_id,
            uncertainties=uncertainties,
        )

    if packet.task == "vacancy_fit_explanation" and packet.search.search_state != "ready":
        return _fallback(
            packet,
            "Поиск вакансий сейчас в резервном или деградированном режиме, поэтому сильное объяснение fit не строится.",
            refs_by_id=refs_by_id,
            uncertainties=uncertainties,
        )

    if "strong_recommendation_claims" in blocked_claims and packet.task in {
        "skill_gap_explanation",
        "career_action_draft",
    }:
        return _fallback(
            packet,
            "Качество датасета не позволяет уверенно ранжировать рекомендации; показываю только проверяемые сигналы.",
            refs_by_id=refs_by_id,
            uncertainties=uncertainties,
        )

    skill_items = [item for item in packet.evidence if item.evidence_type == "skill_gap"]
    if packet.task in {"skill_gap_explanation", "career_action_draft"} and not skill_items:
        return _fallback(
            packet,
            "В пакете нет подтвержденного skill-gap сигнала, поэтому объяснение не строится.",
            refs_by_id=refs_by_id,
            uncertainties=uncertainties,
        )

    if packet.task == "career_action_draft":
        first_skill = skill_items[0]
        skill_name = str(first_skill.metadata.get("skill_name") or first_skill.value or "выбранный навык")
        answer = f"Безопасный следующий шаг: отработать {skill_name} в небольшом практическом задании."
        bullets = [
            f"{_skill_line(item)} [{item.evidence_id}]" for item in skill_items[: packet.output_constraints.max_bullets]
        ]
        return _answer(packet, answer, bullets, skill_items, uncertainties=uncertainties)

    if packet.task == "vacancy_fit_explanation":
        return _fallback(
            packet,
            "В пакете нет конкретной вакансии с подтвержденными навыками, поэтому fit-объяснение не строится.",
            refs_by_id=refs_by_id,
            uncertainties=uncertainties,
        )

    first_skill = skill_items[0]
    skill_name = str(first_skill.metadata.get("skill_name") or first_skill.value or "ключевой навык")
    role = packet.profile.target_role or "целевой роли"
    answer = f"Самый заметный разрыв для цели {role}: {skill_name}."
    bullets = [
        f"{_skill_line(item)} [{item.evidence_id}]" for item in skill_items[: packet.output_constraints.max_bullets]
    ]
    return _answer(packet, answer, bullets, skill_items, uncertainties=uncertainties)


def _dataset_payload(analysis: PersonaAnalysisResponse) -> dict[str, Any]:
    data = analysis.model_dump(mode="json")
    keys = set(EvidenceDatasetContext.model_fields)
    return {key: data.get(key) for key in keys if key in data}


def _plan_context(plan: CareerPlanOut | None) -> EvidencePlanContext:
    if plan is None:
        return EvidencePlanContext()
    open_actions = [
        action
        for action in plan.actions
        if action.status in {"planned", "in_progress"} and action.action_type != "saved_vacancy"
    ]
    next_actions = [
        EvidencePlanActionContext(
            action_id=action.id,
            title=action.title,
            action_type=action.action_type,
            status=action.status,
            priority=action.priority,
            skill_name=action.skill_name,
            hh_vacancy_id=action.hh_vacancy_id,
            vacancy_title=action.vacancy_title,
            recommendation_source=action.recommendation_source,
            dataset_run_id=action.dataset_run_id,
            reason=action.reason,
            evidence=action.evidence,
        )
        for action in sorted(open_actions, key=lambda item: (item.priority, item.id))[:3]
    ]
    return EvidencePlanContext(status=plan.status, action_count=len(plan.actions), next_actions=next_actions)


def _evidence_items(
    analysis: PersonaAnalysisResponse,
    dataset: EvidenceDatasetContext,
    plan: EvidencePlanContext,
    search: EvidenceSearchContext,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    market = analysis.market_summary
    items.append(
        EvidenceItem(
            evidence_id="market:segment_sample",
            evidence_type="market_summary",
            source="persona_analysis.market_summary",
            claim=f"В выбранном сегменте найдено {market.vacancy_count} вакансий.",
            value=market.vacancy_count,
            unit="vacancies",
            confidence=market.confidence or dataset.confidence,
            dataset_run_id=dataset.dataset_run_id,
            generated_at_utc=dataset.generated_at_utc,
            metadata={"sample_size": market.sample_size or market.vacancy_count},
        )
    )

    gap_entries = [entry for entry in analysis.skill_gap if entry.gap]
    gap_entries = sorted(gap_entries, key=lambda entry: (-entry.market_share, entry.skill_name.lower()))
    for entry in gap_entries[:8]:
        share = _percent(entry.market_share)
        items.append(
            EvidenceItem(
                evidence_id=f"skill_gap:{_slug(entry.skill_name)}",
                evidence_type="skill_gap",
                source="persona_analysis.skill_gap",
                claim=(
                    f"Навык {entry.skill_name} встречается примерно в {share}% вакансий выбранного сегмента "
                    "и отсутствует в профиле."
                ),
                value=entry.skill_name,
                unit="skill",
                confidence=market.confidence or dataset.confidence,
                dataset_run_id=dataset.dataset_run_id,
                generated_at_utc=dataset.generated_at_utc,
                metadata={"skill_name": entry.skill_name, "market_share": entry.market_share, "share_percent": share},
            )
        )

    for action in plan.next_actions:
        items.append(
            EvidenceItem(
                evidence_id=f"plan_action:{action.action_id}",
                evidence_type="plan_action",
                source="career_plan.actions",
                claim=f'В плане есть действие "{action.title}" со статусом "{action.status}".',
                value=action.title,
                unit="action",
                confidence=dataset.confidence,
                dataset_run_id=action.dataset_run_id or dataset.dataset_run_id,
                generated_at_utc=dataset.generated_at_utc,
                metadata={"action_type": action.action_type, "skill_name": action.skill_name},
            )
        )

    if search.search_state != "ready":
        items.append(
            EvidenceItem(
                evidence_id="search:runtime_state",
                evidence_type="search_runtime",
                source="app_state.meilisearch_status",
                claim=f"Поиск вакансий сейчас работает в режиме {search.search_state}.",
                value=search.search_state,
                unit="state",
                confidence="high",
                dataset_run_id=dataset.dataset_run_id,
                generated_at_utc=dataset.generated_at_utc,
                metadata={"index_status": search.index_status, "degraded_reason": search.degraded_reason},
            )
        )

    return items


def _blocked_claims(dataset: EvidenceDatasetContext, search: EvidenceSearchContext) -> list[str]:
    blocked: list[str] = []
    eligibility = dataset.product_eligibility or {}
    if not _eligible(eligibility, "salary"):
        blocked.append("salary_claims")
    if not _eligible(eligibility, "trends") or dataset.date_semantics_status not in {None, "passed"}:
        blocked.append("historical_trend_claims")
    if not _eligible(eligibility, "recommendations"):
        blocked.append("strong_recommendation_claims")
    if search.search_state != "ready":
        blocked.append("strong_vacancy_fit_claims")
    return sorted(set(blocked))


def _packet_warnings(
    analysis: PersonaAnalysisResponse,
    dataset: EvidenceDatasetContext,
    search: EvidenceSearchContext,
) -> list[str]:
    warnings = list(analysis.warnings) + list(search.warnings)
    if dataset.freshness in {"stale", "unknown"}:
        warnings.append(f"dataset_freshness:{dataset.freshness}")
    if dataset.date_semantics_status not in {None, "passed"}:
        warnings.append(f"date_semantics:{dataset.date_semantics_status}")
    return sorted({warning for warning in warnings if warning})


def _uncertainties(packet: EvidencePacketOut) -> list[str]:
    uncertainties = list(packet.warnings)
    if packet.dataset.confidence in {None, "low", "unknown"}:
        uncertainties.append("dataset_confidence_low")
    if packet.search.search_state != "ready":
        uncertainties.append(f"search_state:{packet.search.search_state}")
    return sorted({value for value in uncertainties if value})


def _fallback(
    packet: EvidencePacketOut,
    answer: str,
    *,
    refs_by_id: dict[str, EvidenceItem],
    uncertainties: list[str],
    status: EvidenceExplainerStatus = "fallback",
) -> EvidenceExplainerOut:
    refs = _refs(list(refs_by_id.values())[:1])
    return EvidenceExplainerOut(
        version=EVIDENCE_EXPLAINER_VERSION,
        packet_version=packet.version,
        task=packet.task,
        surface=packet.surface,
        status=status,
        answer=answer,
        evidence_refs=refs,
        uncertainties=uncertainties,
        blocked_claims=packet.output_constraints.blocked_claims,
        human_review_required=status != "answered",
    )


def _answer(
    packet: EvidencePacketOut,
    answer: str,
    bullets: list[str],
    evidence_items: list[EvidenceItem],
    *,
    uncertainties: list[str],
) -> EvidenceExplainerOut:
    return EvidenceExplainerOut(
        version=EVIDENCE_EXPLAINER_VERSION,
        packet_version=packet.version,
        task=packet.task,
        surface=packet.surface,
        status="answered",
        answer=answer,
        bullets=bullets,
        evidence_refs=_refs(evidence_items[: packet.output_constraints.max_bullets]),
        uncertainties=uncertainties,
        blocked_claims=packet.output_constraints.blocked_claims,
        human_review_required=False,
    )


def _refs(items: list[EvidenceItem]) -> list[EvidenceRefOut]:
    return [EvidenceRefOut(evidence_id=item.evidence_id, claim=item.claim) for item in items]


def _eligible(product_eligibility: dict[str, Any], key: str) -> bool:
    value = product_eligibility.get(key)
    if isinstance(value, dict):
        return value.get("eligible") is True
    return value is True


def _normalize_search_state(value: str | None) -> EvidenceSearchState:
    if value == "degraded":
        return "degraded"
    if value == "fallback":
        return "fallback"
    if value == "unavailable":
        return "unavailable"
    return "ready"


def _skill_line(item: EvidenceItem) -> str:
    skill_name = str(item.metadata.get("skill_name") or item.value or "Навык")
    share = item.metadata.get("share_percent")
    if isinstance(share, int | float):
        return f"{skill_name}: около {share}% вакансий сегмента, навыка нет в профиле."
    return item.claim


def _percent(value: float) -> int:
    return int(round(float(value) * 100))


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "_", value.strip().lower()).strip("_")
    return normalized or "unknown"
