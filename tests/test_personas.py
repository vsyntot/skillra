"""Unit tests for persona demand and gap analysis."""

import pandas as pd

from src.skillra_pda import personas


def test_skill_gap_for_persona_marks_missing_and_existing_skills():
    df = pd.DataFrame(
        {
            "primary_role": ["data", "data", "data"],
            "grade": ["junior", "junior", "junior"],
            "skill_sql": [True, True, False],
            "has_python": [True, False, False],
            "skill_statistics": [False, True, False],
        }
    )

    persona = personas.Persona(
        name="student",
        description="",
        current_skills=["skill_sql", "skill_statistics"],
        target_role="data",
        target_grade="junior",
    )

    gap = personas.skill_gap_for_persona(df, persona, min_share=0.2, top_n=None)

    sql = gap.loc[gap["skill_name"] == "skill_sql"].iloc[0]
    assert bool(sql["persona_has"]) is True
    assert bool(sql["gap"]) is False

    python = gap.loc[gap["skill_name"] == "has_python"].iloc[0]
    assert bool(python["persona_has"]) is False
    assert bool(python["gap"]) is True

    statistics = gap.loc[gap["skill_name"] == "skill_statistics"].iloc[0]
    assert bool(statistics["persona_has"]) is True
    assert bool(statistics["gap"]) is False


def test_build_skill_demand_profile_filters_and_sorts():
    df = pd.DataFrame(
        {
            "primary_role": ["data", "data", "other"],
            "grade": ["junior", "junior", "junior"],
            "skill_sql": [True, True, True],
            "has_python": [True, False, False],
            "skill_statistics": [True, True, False],
        }
    )

    persona = personas.Persona(
        name="student",
        description="",
        current_skills=[],
        target_role="data",
        target_grade="junior",
    )

    demand = personas.build_skill_demand_profile(df, persona, min_share=0.2)

    assert list(demand["skill_name"]) == ["skill_sql", "skill_statistics", "has_python"]
    assert demand["market_share"].tolist() == [2 / 2, 2 / 2, 1 / 2]
