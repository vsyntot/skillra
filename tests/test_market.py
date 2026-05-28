from __future__ import annotations

import pandas as pd

from src.skillra_pda.market import build_market_view, market_confidence


def test_build_market_view_exposes_salary_coverage_and_confidence() -> None:
    df = pd.DataFrame(
        {
            "primary_role": ["analyst", "analyst", "analyst"],
            "grade_final": ["junior", "junior", "junior"],
            "city_tier": ["Moscow", "Moscow", "Moscow"],
            "country": ["Russia", "Russia", "Russia"],
            "region": ["Moscow", "Moscow", "Moscow"],
            "city_normalized": ["Moscow", "Moscow", "Moscow"],
            "geo_scope": ["mixed", "mixed", "mixed"],
            "salary_mid_rub_capped": [100_000, None, 160_000],
            "is_junior_friendly": [True, False, True],
            "is_remote": [True, True, False],
            "tech_stack_size": [3, 4, 5],
            "skill_sql": [True, True, False],
        }
    )

    market_view = build_market_view(df)
    row = market_view.iloc[0]

    assert row["vacancy_count"] == 3
    assert row["sample_size"] == 3
    assert row["salary_sample_size"] == 2
    assert row["salary_coverage_share"] == 2 / 3
    assert row["confidence"] == "low"
    assert row["salary_median"] == 130_000
    assert row["country"] == "Russia"
    assert row["city_normalized"] == "Moscow"


def test_build_market_view_uses_salary_disclosed_for_salary_metrics() -> None:
    df = pd.DataFrame(
        {
            "primary_role": ["analyst", "analyst", "analyst"],
            "grade_final": ["junior", "junior", "junior"],
            "city_tier": ["Moscow", "Moscow", "Moscow"],
            "salary_mid_rub_capped": [100_000, 200_000, None],
            "salary_disclosed": [True, False, False],
        }
    )

    market_view = build_market_view(df)
    row = market_view.iloc[0]

    assert row["vacancy_count"] == 3
    assert row["salary_sample_size"] == 1
    assert row["salary_coverage_share"] == 1 / 3
    assert row["salary_median"] == 100_000


def test_market_confidence_thresholds() -> None:
    assert market_confidence(100, 40, 0.4) == "high"
    assert market_confidence(25, 6, 0.24) == "medium"
    assert market_confidence(10, 10, 1.0) == "low"
