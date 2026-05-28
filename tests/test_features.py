"""Unit tests for key feature engineering helpers."""

import pandas as pd

from src.skillra_pda import features


def test_add_city_tier_assigns_expected_buckets_without_side_effects():
    df = pd.DataFrame(
        {
            "city": ["Москва", "Санкт-Петербург", "Казань", "Алматы"],
            "vacancy_id": [1, 2, 3, 4],
        }
    )

    result = features.add_city_tier(df.copy())

    assert set(result.columns) == set(df.columns) | {"city_tier"}
    assert result["vacancy_id"].tolist() == df["vacancy_id"].tolist()
    assert result["city_tier"].tolist() == ["Moscow", "SPb", "Million+", "KZ/Other"]


def test_add_geography_features_normalizes_city_country_and_scope():
    df = pd.DataFrame(
        {
            "city": ["Москва", "Алматы", "Минск", ""],
            "search_area_id": [1, 159, 40, 113],
            "work_mode": ["office", "remote", "hybrid", "unknown"],
        }
    )

    result = features.add_geography_features(df)

    assert result["country"].tolist() == ["Russia", "Kazakhstan", "Belarus", "Russia"]
    assert result["city_normalized"].tolist() == ["Moscow", "Almaty", "Minsk", "unknown"]
    assert result["geo_scope"].tolist() == ["local", "remote", "mixed", "unknown"]
    assert result["remote_geo_eligible"].tolist() == [False, True, True, False]


def test_add_primary_role_chooses_priority_role_and_keeps_other_columns():
    df = pd.DataFrame(
        {
            "role_ml": [False, True, False],
            "role_analyst": [True, True, False],
            "role_backend": [False, False, True],
            "city": ["Moscow", "SPb", "Kazan"],
        }
    )

    result = features.add_primary_role(df.copy())

    assert set(result.columns) == set(df.columns) | {"primary_role"}
    assert result["city"].tolist() == df["city"].tolist()
    assert list(result["primary_role"]) == ["analyst", "ml", "backend"]


def test_add_primary_role_uses_title_fallback_when_role_flags_missing():
    df = pd.DataFrame(
        {
            "title": ["Python Developer", "ML Engineer", "Системный аналитик"],
            "city": ["Moscow", "SPb", "Kazan"],
        }
    )

    result = features.add_primary_role(df.copy())

    assert list(result["primary_role"]) == ["backend", "ml", "analyst"]
