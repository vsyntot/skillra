"""Tests for Pydantic input validation constraints added in Sprint-002 (TASK-05).

Verifies that the DoS-prevention limits enforced by schemas.py work correctly:
- PersonaProfile: current_skills max 200 items, skill name max 100 chars
- UserProfileIn: current_skills max 200 items, skill name max 100 chars
See GAP-N05 / SPRINT-003.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings  # noqa: E402
from skillra_api.db import Base  # noqa: E402
from skillra_api.main import create_app  # noqa: E402


@pytest.fixture()
def validation_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    """Test client with minimal valid parquet files for validation tests."""
    features_path = tmp_path / "hh_features.parquet"
    market_view_path = tmp_path / "market_view.parquet"

    features_df = pd.DataFrame(
        {
            "primary_role": ["data"] * 5,
            "grade_final": ["senior"] * 5,
            "skill_python": [1, 1, 1, 1, 1],
            "salary_mid_rub_capped": [100_000] * 5,
        }
    )
    features_df.to_parquet(features_path)

    market_view_df = pd.DataFrame(
        {
            "primary_role": ["data"],
            "grade_final": ["senior"],
            "vacancy_count": [5],
            "salary_median": [100_000.0],
            "salary_q25": [80_000.0],
            "salary_q75": [120_000.0],
            "remote_share": [0.5],
            "junior_friendly_share": [0.1],
            "median_tech_stack_size": [6.0],
        }
    )
    market_view_df.to_parquet(market_view_path)

    settings = Settings(
        log_level="CRITICAL",
        features_path=str(features_path),
        market_view_path=str(market_view_path),
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'validation.db'}",
    )
    app = create_app(settings)

    async def _prepare_database() -> None:
        async with app.state.db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    with TestClient(app) as client:
        client.portal.call(_prepare_database)
        client.headers.update(auth_headers)
        yield client


# ---------------------------------------------------------------------------
# PersonaProfile validation — POST /v1/persona/analyze
# ---------------------------------------------------------------------------


def _analyze_payload(skills: list[str], role: str = "data") -> dict:
    return {
        "name": "test",
        "description": "test",
        "current_skills": skills,
        "target_role": role,
        "constraints": {},
        "goals": [],
        "limitations": [],
    }


def test_persona_analyze_200_skills_accepted(validation_client: TestClient) -> None:
    """Exactly 200 skills should be accepted (boundary: max allowed)."""
    skills = [f"skill{i}" for i in range(200)]
    response = validation_client.post("/v1/persona/analyze", json=_analyze_payload(skills))
    # 200 OK or 422 for unknown skills — but NOT 422 for too many skills
    data = response.json()
    if response.status_code == 422:
        errors = data.get("details", {}).get("errors", [])
        for err in errors:
            assert "too_long" not in err.get(
                "type", ""
            ), f"200 skills should not trigger max_length validation but got: {err}"


def test_persona_analyze_201_skills_rejected(validation_client: TestClient) -> None:
    """201 skills must be rejected with 422 Unprocessable Entity."""
    skills = [f"skill{i}" for i in range(201)]
    response = validation_client.post("/v1/persona/analyze", json=_analyze_payload(skills))
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    assert "body" not in data["details"]
    assert data["details"]["body_present"] is True
    errors = data["details"]["errors"]
    assert any(
        "too_long" in err.get("type", "") for err in errors
    ), f"Expected too_long error for 201 skills, got: {errors}"


def test_persona_analyze_skill_name_100_chars_accepted(validation_client: TestClient) -> None:
    """A skill name of exactly 100 chars should be accepted."""
    long_skill = "a" * 100
    response = validation_client.post("/v1/persona/analyze", json=_analyze_payload([long_skill]))
    data = response.json()
    if response.status_code == 422:
        errors = data.get("details", {}).get("errors", [])
        for err in errors:
            assert "too_long" not in err.get(
                "type", ""
            ), f"100-char skill should not trigger max_length validation but got: {err}"


def test_persona_analyze_skill_name_101_chars_rejected(validation_client: TestClient) -> None:
    """A skill name of 101 chars must be rejected with 422."""
    long_skill = "a" * 101
    response = validation_client.post("/v1/persona/analyze", json=_analyze_payload([long_skill]))
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    errors = data["details"]["errors"]
    assert any(
        "too_long" in err.get("type", "") or "string_too_long" in err.get("type", "") for err in errors
    ), f"Expected too_long error for 101-char skill, got: {errors}"


# ---------------------------------------------------------------------------
# UserProfileIn validation — PUT /v1/users/{id}/profile
# ---------------------------------------------------------------------------


def _profile_payload(skills: list[str]) -> dict:
    return {
        "current_skills": skills,
        "target_role": "data",
    }


def test_user_profile_200_skills_accepted(validation_client: TestClient) -> None:
    """Exactly 200 skills should be accepted for UserProfileIn."""
    skills = [f"python{i}" for i in range(200)]
    response = validation_client.put("/v1/users/12345/profile", json=_profile_payload(skills))
    data = response.json()
    if response.status_code == 422:
        errors = data.get("details", {}).get("errors", [])
        for err in errors:
            assert "too_long" not in err.get(
                "type", ""
            ), f"200 skills should not trigger max_length validation but got: {err}"


def test_user_profile_201_skills_rejected(validation_client: TestClient) -> None:
    """201 skills must be rejected with 422 for UserProfileIn."""
    skills = [f"python{i}" for i in range(201)]
    response = validation_client.put("/v1/users/12345/profile", json=_profile_payload(skills))
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    errors = data["details"]["errors"]
    assert any(
        "too_long" in err.get("type", "") for err in errors
    ), f"Expected too_long error for 201 skills, got: {errors}"


def test_user_profile_skill_name_101_chars_rejected(validation_client: TestClient) -> None:
    """A skill name of 101 chars must be rejected for UserProfileIn."""
    long_skill = "z" * 101
    response = validation_client.put("/v1/users/12345/profile", json=_profile_payload([long_skill]))
    assert response.status_code == 422
    data = response.json()
    assert data["error_code"] == "VALIDATION_ERROR"
