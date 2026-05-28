"""Weekly market snapshot builder and trend helpers."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .config import load_noisy_skills

logger = logging.getLogger(__name__)

SNAPSHOT_COLUMNS = [
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


def _normalize_week_start(value: date | None) -> date:
    current = value or date.today()
    return current - timedelta(days=current.weekday())


def _snapshot_filename(week_start: date) -> str:
    iso_year, iso_week, _ = week_start.isocalendar()
    return f"{iso_year}-W{iso_week:02d}.parquet"


def _grade_column(df: pd.DataFrame) -> str:
    if "grade_final" in df.columns:
        return "grade_final"
    if "grade" in df.columns:
        return "grade"
    raise ValueError("expected column grade or grade_final for weekly snapshot")


def _salary_column(df: pd.DataFrame) -> str:
    for column in ("salary_mid_rub_capped", "salary_mid_rub", "salary_mid"):
        if column in df.columns:
            return column
    raise ValueError("expected salary_mid_rub_capped, salary_mid_rub, or salary_mid for weekly snapshot")


def _clean_skill_name(column: str) -> str:
    for prefix in ("skill_", "has_"):
        if column.startswith(prefix):
            return column.removeprefix(prefix)
    return column


def _skill_columns(df: pd.DataFrame) -> list[str]:
    noisy = load_noisy_skills()
    normalized_noisy = {_clean_skill_name(skill) for skill in noisy}
    return [
        column
        for column in df.columns
        if (column.startswith("skill_") or column.startswith("has_"))
        and column not in noisy
        and _clean_skill_name(column) not in normalized_noisy
    ]


def _string_series(series: pd.Series, default: str = "unknown") -> pd.Series:
    return series.astype("object").fillna(default).astype(str)


def _string_column(df: pd.DataFrame, column: str, default: str = "unknown") -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index)
    return _string_series(df[column], default)


def _derive_domain(df: pd.DataFrame) -> pd.Series:
    if "domain" in df.columns:
        return _string_series(df["domain"])

    domain_columns = [column for column in df.columns if column.startswith("domain_")]
    if not domain_columns:
        return pd.Series("unknown", index=df.index)

    domain_flags = df[domain_columns].fillna(False).astype(bool)

    def first_domain(row: pd.Series) -> str:
        for column in domain_columns:
            if bool(row[column]):
                return column.removeprefix("domain_")
        return "unknown"

    return domain_flags.apply(first_domain, axis=1)


def _top_skills(group: pd.DataFrame, skill_columns: list[str]) -> list[str]:
    if not skill_columns:
        return []

    counts = group[skill_columns].fillna(False).astype(bool).sum(axis=0)
    counts_by_skill: dict[str, int] = {}
    for column, count in counts.items():
        skill_name = _clean_skill_name(column)
        count_value = int(count)
        if count_value > counts_by_skill.get(skill_name, 0):
            counts_by_skill[skill_name] = count_value

    rows = [(skill, count) for skill, count in counts_by_skill.items() if count > 0]
    rows.sort(key=lambda item: (-item[1], item[0]))
    return [skill for skill, _ in rows[:10]]


def _empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(columns=SNAPSHOT_COLUMNS)


def build_weekly_snapshot(
    features_path: Path,
    output_dir: Path,
    week_start: date | None = None,
) -> Path:
    """Build and persist a weekly aggregate snapshot from a features parquet file."""

    resolved_week_start = _normalize_week_start(week_start)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _snapshot_filename(resolved_week_start)

    logger.info("Building weekly market snapshot from %s", features_path)
    features_df = pd.read_parquet(features_path)
    if features_df.empty:
        _empty_snapshot().to_parquet(output_path, index=False)
        logger.info("Saved empty weekly market snapshot to %s", output_path)
        return output_path

    if "primary_role" not in features_df.columns:
        raise ValueError("expected column primary_role for weekly snapshot")

    grade_col = _grade_column(features_df)
    salary_col = _salary_column(features_df)
    skill_cols = _skill_columns(features_df)

    temp = pd.DataFrame(
        {
            "week_start": resolved_week_start,
            "role": _string_column(features_df, "primary_role"),
            "grade": _string_column(features_df, grade_col),
            "city_tier": _string_column(features_df, "city_tier"),
            "work_mode": _string_column(features_df, "work_mode"),
            "domain": _derive_domain(features_df),
            "_salary": pd.to_numeric(features_df[salary_col], errors="coerce"),
        }
    )
    if skill_cols:
        temp[skill_cols] = features_df[skill_cols]

    group_cols = ["week_start", "role", "grade", "city_tier", "work_mode", "domain"]
    records: list[dict[str, Any]] = []
    for keys, group in temp.groupby(group_cols, dropna=False, observed=True, sort=True):
        salary = group["_salary"].dropna()
        record = dict(zip(group_cols, keys))
        record.update(
            {
                "vacancy_count": int(len(group)),
                "salary_p25": float(salary.quantile(0.25)) if not salary.empty else None,
                "salary_p50": float(salary.quantile(0.50)) if not salary.empty else None,
                "salary_p75": float(salary.quantile(0.75)) if not salary.empty else None,
                "skill_top10": _top_skills(group, skill_cols),
            }
        )
        records.append(record)

    snapshot_df = pd.DataFrame(records, columns=SNAPSHOT_COLUMNS)
    snapshot_df.to_parquet(output_path, index=False)
    logger.info("Saved weekly market snapshot rows=%d path=%s", len(snapshot_df), output_path)
    return output_path


def load_snapshot_history(snapshots_dir: Path) -> pd.DataFrame:
    """Load all weekly snapshots into one DataFrame sorted by ``week_start``."""

    if not snapshots_dir.exists():
        return _empty_snapshot()

    frames = [pd.read_parquet(path) for path in sorted(snapshots_dir.glob("*.parquet"))]
    if not frames:
        return _empty_snapshot()

    history = pd.concat(frames, ignore_index=True)
    if "week_start" in history.columns:
        history["_week_sort"] = pd.to_datetime(history["week_start"], errors="coerce")
        history = history.sort_values("_week_sort").drop(columns=["_week_sort"])
    return history.reset_index(drop=True)


def _skill_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = [part.strip() for part in stripped.split(",")]
        return [_clean_skill_name(str(skill).strip()) for skill in decoded if str(skill).strip()]
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        return [_clean_skill_name(str(skill).strip()) for skill in value if str(skill).strip()]
    return [_clean_skill_name(str(value).strip())] if str(value).strip() else []


def _filter_history(
    history_df: pd.DataFrame,
    role: str | None = None,
    grade: str | None = None,
) -> pd.DataFrame:
    filtered = history_df.copy()
    if role is not None and "role" in filtered.columns:
        filtered = filtered[filtered["role"].astype(str) == role]
    if grade is not None and "grade" in filtered.columns:
        filtered = filtered[filtered["grade"].astype(str) == grade]
    return filtered


def compute_skill_demand_trend(
    history_df: pd.DataFrame,
    skill: str,
    role: str | None = None,
    grade: str | None = None,
    weeks: int = 12,
) -> pd.DataFrame:
    """Return weekly vacancy counts for rows where ``skill`` appears in ``skill_top10``."""

    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    if history_df.empty:
        return pd.DataFrame(columns=["week_start", "vacancy_count"])

    skill_name = _clean_skill_name(skill.strip()).lower()
    filtered = _filter_history(history_df, role=role, grade=grade)
    if filtered.empty or "skill_top10" not in filtered.columns:
        return pd.DataFrame(columns=["week_start", "vacancy_count"])

    mask = filtered["skill_top10"].apply(lambda value: skill_name in {item.lower() for item in _skill_list(value)})
    matched = filtered.loc[mask]
    if matched.empty:
        return pd.DataFrame(columns=["week_start", "vacancy_count"])

    trend = matched.groupby("week_start", as_index=False, observed=True)["vacancy_count"].sum()
    trend["_week_sort"] = pd.to_datetime(trend["week_start"], errors="coerce")
    trend = trend.sort_values("_week_sort").drop(columns=["_week_sort"]).tail(weeks)
    return trend.reset_index(drop=True)


def compute_salary_trend(
    history_df: pd.DataFrame,
    role: str,
    grade: str,
    weeks: int = 12,
) -> pd.DataFrame:
    """Return weekly weighted salary_p50 trend for a role and grade."""

    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    if history_df.empty:
        return pd.DataFrame(columns=["week_start", "salary_p50"])

    filtered = _filter_history(history_df, role=role, grade=grade)
    if filtered.empty or "salary_p50" not in filtered.columns:
        return pd.DataFrame(columns=["week_start", "salary_p50"])

    rows: list[dict[str, Any]] = []
    for week, group in filtered.groupby("week_start", observed=True, sort=False):
        salary = pd.to_numeric(group["salary_p50"], errors="coerce")
        valid = group.loc[salary.notna()].copy()
        if valid.empty:
            salary_p50 = None
        elif "vacancy_count" in valid.columns:
            weights = pd.to_numeric(valid["vacancy_count"], errors="coerce").fillna(0)
            if weights.sum() > 0:
                salary_p50 = float((salary.loc[valid.index] * weights).sum() / weights.sum())
            else:
                salary_p50 = float(salary.loc[valid.index].mean())
        else:
            salary_p50 = float(salary.loc[valid.index].mean())
        rows.append({"week_start": week, "salary_p50": salary_p50})

    trend = pd.DataFrame(rows, columns=["week_start", "salary_p50"])
    trend["_week_sort"] = pd.to_datetime(trend["week_start"], errors="coerce")
    trend = trend.sort_values("_week_sort").drop(columns=["_week_sort"]).tail(weeks)
    return trend.reset_index(drop=True)
