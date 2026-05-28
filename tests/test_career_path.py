from __future__ import annotations

from datetime import date

import pandas as pd

from src.skillra_pda.career_path import GRADE_ORDER, build_career_graph, recommend_next_step


def _career_features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "primary_role": ["analyst", "analyst", "analyst", "analyst", "analyst", "backend"],
            "grade_final": ["junior", "junior", "middle", "middle", "senior", "middle"],
            "salary_mid_rub_capped": [100_000, 120_000, 180_000, 220_000, 320_000, 250_000],
            "skill_sql": [True, True, True, True, True, False],
            "skill_excel": [True, True, False, False, False, False],
            "has_python": [False, False, True, True, True, True],
            "skill_tableau": [False, False, True, False, True, False],
            "skill_airflow": [False, False, False, True, True, False],
        }
    )


def test_build_career_graph_data_analyst() -> None:
    graph = build_career_graph(_career_features(), "Data Analyst")

    assert len(graph) == 2
    junior_to_middle = graph[0]
    assert junior_to_middle.from_node.grade == "junior"
    assert junior_to_middle.to_node.grade == "middle"
    assert junior_to_middle.from_node.salary_p50 == 110_000
    assert junior_to_middle.to_node.salary_p50 == 200_000
    assert round(junior_to_middle.salary_delta_pct or 0, 2) == 81.82
    assert junior_to_middle.skills_to_add == ["python", "airflow", "tableau"]


def test_recommend_next_step() -> None:
    history = pd.DataFrame(
        [
            {
                "week_start": date(2026, 5, 4),
                "role": "analyst",
                "grade": "middle",
                "vacancy_count": 5,
            },
            {
                "week_start": date(2026, 5, 11),
                "role": "analyst",
                "grade": "middle",
                "vacancy_count": 8,
            },
        ]
    )

    recommendation = recommend_next_step(
        current_role="Data Analyst",
        current_grade="junior",
        user_skills=["sql", "excel"],
        features_df=_career_features(),
        history_df=history,
    )

    assert recommendation["next_grade"] == "middle"
    assert recommendation["salary_current_p50"] == 110_000
    assert recommendation["salary_next_p50"] == 200_000
    assert recommendation["skills_to_add"] == ["python", "airflow", "tableau"]
    assert recommendation["demand_trend"] == "growing"


def test_grade_order_correct() -> None:
    assert GRADE_ORDER["jun"] < GRADE_ORDER["middle"] < GRADE_ORDER["senior"] < GRADE_ORDER["lead"]
    assert GRADE_ORDER["jun"] == GRADE_ORDER["junior"]
