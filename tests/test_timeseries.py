from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.skillra_pda.timeseries import (
    build_weekly_snapshot,
    compute_salary_trend,
    compute_skill_demand_trend,
    load_snapshot_history,
)


def _features_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "primary_role": ["analyst", "analyst", "analyst", "backend"],
            "grade_final": ["junior", "junior", "middle", "middle"],
            "city_tier": ["Moscow", "Moscow", "SPb", "Moscow"],
            "work_mode": ["remote", "remote", "hybrid", "office"],
            "domain_finance": [True, True, False, False],
            "domain_it_product": [False, False, True, True],
            "salary_mid_rub_capped": [100_000, 140_000, 220_000, 260_000],
            "skill_sql": [True, True, True, False],
            "has_python": [False, True, True, True],
            "skill_excel": [True, False, False, False],
        }
    )


def test_build_weekly_snapshot_creates_parquet(tmp_path: Path) -> None:
    features_path = tmp_path / "features.parquet"
    _features_df().to_parquet(features_path, index=False)

    output_path = build_weekly_snapshot(features_path, tmp_path / "market_snapshots", week_start=date(2026, 5, 19))

    assert output_path.name == "2026-W21.parquet"
    snapshot = pd.read_parquet(output_path)
    assert list(snapshot.columns) == [
        "week_start",
        "role",
        "grade",
        "city_tier",
        "work_mode",
        "domain",
        "vacancy_count",
        "salary_p25",
        "salary_p50",
        "salary_p75",
        "skill_top10",
    ]
    analyst_junior = snapshot.loc[(snapshot["role"] == "analyst") & (snapshot["grade"] == "junior")].iloc[0]
    assert analyst_junior["vacancy_count"] == 2
    assert analyst_junior["salary_p50"] == 120_000
    assert list(analyst_junior["skill_top10"]) == ["sql", "excel", "python"]


def test_build_weekly_snapshot_handles_categorical_missing_values(tmp_path: Path) -> None:
    features = _features_df()
    features["primary_role"] = pd.Categorical(
        ["analyst", None, "analyst", "backend"],
        categories=["analyst", "backend"],
    )
    features["grade_final"] = pd.Categorical(
        ["junior", "junior", None, "middle"],
        categories=["junior", "middle"],
    )
    features["city_tier"] = pd.Categorical(
        ["Moscow", None, "SPb", "Moscow"],
        categories=["Moscow", "SPb"],
    )
    features["work_mode"] = pd.Categorical(
        ["remote", "remote", None, "office"],
        categories=["remote", "office"],
    )
    features_path = tmp_path / "features.parquet"
    features.to_parquet(features_path, index=False)

    output_path = build_weekly_snapshot(features_path, tmp_path / "market_snapshots", week_start=date(2026, 5, 19))

    snapshot = pd.read_parquet(output_path)
    assert "unknown" in set(snapshot["role"])
    assert "unknown" in set(snapshot["grade"])
    assert "unknown" in set(snapshot["city_tier"])
    assert "unknown" in set(snapshot["work_mode"])


def test_load_snapshot_history_sorted(tmp_path: Path) -> None:
    snapshots_dir = tmp_path / "market_snapshots"
    snapshots_dir.mkdir()
    pd.DataFrame(
        [{"week_start": date(2026, 5, 18), "role": "analyst", "grade": "junior", "vacancy_count": 2}]
    ).to_parquet(snapshots_dir / "2026-W21.parquet", index=False)
    pd.DataFrame(
        [{"week_start": date(2026, 5, 11), "role": "analyst", "grade": "junior", "vacancy_count": 1}]
    ).to_parquet(snapshots_dir / "2026-W20.parquet", index=False)

    history = load_snapshot_history(snapshots_dir)

    assert history["week_start"].tolist() == [date(2026, 5, 11), date(2026, 5, 18)]


def test_compute_skill_demand_trend() -> None:
    history = pd.DataFrame(
        [
            {
                "week_start": date(2026, 5, 4),
                "role": "analyst",
                "grade": "junior",
                "vacancy_count": 3,
                "skill_top10": ["sql", "python"],
            },
            {
                "week_start": date(2026, 5, 4),
                "role": "backend",
                "grade": "middle",
                "vacancy_count": 5,
                "skill_top10": ["python"],
            },
            {
                "week_start": date(2026, 5, 11),
                "role": "analyst",
                "grade": "junior",
                "vacancy_count": 7,
                "skill_top10": '["sql", "excel"]',
            },
        ]
    )

    trend = compute_skill_demand_trend(history, "skill_sql", role="analyst", weeks=12)

    assert trend.to_dict(orient="records") == [
        {"week_start": date(2026, 5, 4), "vacancy_count": 3},
        {"week_start": date(2026, 5, 11), "vacancy_count": 7},
    ]


def test_compute_salary_trend() -> None:
    history = pd.DataFrame(
        [
            {
                "week_start": date(2026, 5, 4),
                "role": "analyst",
                "grade": "junior",
                "vacancy_count": 1,
                "salary_p50": 100_000,
            },
            {
                "week_start": date(2026, 5, 4),
                "role": "analyst",
                "grade": "junior",
                "vacancy_count": 3,
                "salary_p50": 140_000,
            },
            {
                "week_start": date(2026, 5, 11),
                "role": "analyst",
                "grade": "junior",
                "vacancy_count": 2,
                "salary_p50": 160_000,
            },
        ]
    )

    trend = compute_salary_trend(history, role="analyst", grade="junior", weeks=1)

    assert trend.to_dict(orient="records") == [{"week_start": date(2026, 5, 11), "salary_p50": 160_000.0}]
