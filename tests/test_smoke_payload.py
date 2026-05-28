from __future__ import annotations

from scripts.smoke_skillra_platform import _build_persona_payload


def _build_filters() -> dict[str, str | None]:
    return {
        "role": "Data Analyst",
        "grade": None,
        "city_tier": None,
        "work_mode": None,
        "domain": None,
    }


def _assert_payload_required_fields(payload: dict[str, object]) -> None:
    for field in ("location", "experience", "target_role", "work_format"):
        assert field in payload


def test_build_persona_payload_uses_single_skill_when_available() -> None:
    meta = {"skills": ["python", "sql"], "roles": ["Data Analyst"]}

    payload = _build_persona_payload(meta, _build_filters())

    assert len(payload["current_skills"]) == 1
    _assert_payload_required_fields(payload)


def test_build_persona_payload_uses_empty_skills_when_only_one_available() -> None:
    meta = {"skills": ["python"], "roles": ["Data Analyst"]}

    payload = _build_persona_payload(meta, _build_filters())

    assert payload["current_skills"] == []
    _assert_payload_required_fields(payload)
