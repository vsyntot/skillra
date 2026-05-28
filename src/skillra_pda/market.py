"""Market-level aggregations for Skillra Navigator views."""

from __future__ import annotations

from typing import Iterable

import pandas as pd

CONFIDENCE_HIGH_MIN_ROWS = 80
CONFIDENCE_HIGH_MIN_SALARY_ROWS = 30
CONFIDENCE_HIGH_MIN_SALARY_COVERAGE = 0.30
CONFIDENCE_MEDIUM_MIN_ROWS = 20
CONFIDENCE_MEDIUM_MIN_SALARY_ROWS = 5
CONFIDENCE_MEDIUM_MIN_SALARY_COVERAGE = 0.10


def market_confidence(
    vacancy_count: int,
    salary_sample_size: int | None = None,
    salary_coverage_share: float | None = None,
) -> str:
    """Return a compact confidence label for user-facing market advice."""

    salary_rows = int(salary_sample_size or 0)
    coverage = float(salary_coverage_share or 0.0)
    if (
        vacancy_count >= CONFIDENCE_HIGH_MIN_ROWS
        and salary_rows >= CONFIDENCE_HIGH_MIN_SALARY_ROWS
        and coverage >= CONFIDENCE_HIGH_MIN_SALARY_COVERAGE
    ):
        return "high"
    if (
        vacancy_count >= CONFIDENCE_MEDIUM_MIN_ROWS
        and salary_rows >= CONFIDENCE_MEDIUM_MIN_SALARY_ROWS
        and coverage >= CONFIDENCE_MEDIUM_MIN_SALARY_COVERAGE
    ):
        return "medium"
    return "low"


def _derive_domain(df: pd.DataFrame, domain_cols: Iterable[str]) -> pd.Series:
    """Return the primary domain label from one-hot domain columns."""

    if not domain_cols:
        return pd.Series("unknown", index=df.index)

    domain_flags = df[domain_cols].fillna(False).astype(bool)

    def _first_domain(row: pd.Series) -> str:
        for col in domain_cols:
            if bool(row[col]):
                return col.replace("domain_", "")
        return "unknown"

    return domain_flags.apply(_first_domain, axis=1)


def _format_top_skills(row: pd.Series) -> str:
    """Format top skills and their shares from a row of mean values."""

    non_zero = row[row > 0].sort_values(ascending=False)
    if non_zero.empty:
        return ""

    top_n = min(5, len(non_zero))

    def _clean_name(col: str) -> str:
        if col.startswith("skill_"):
            return col.replace("skill_", "")
        if col.startswith("has_"):
            return col.replace("has_", "")
        return col

    return ", ".join([f"{_clean_name(col)} ({share:.0%})" for col, share in non_zero.head(top_n).items()])


def _quantile_or_na(series: pd.Series, quantile: float) -> float | object:
    clean = series.dropna()
    if clean.empty:
        return pd.NA
    return float(clean.quantile(quantile))


def _median_or_na(series: pd.Series) -> float | object:
    clean = series.dropna()
    if clean.empty:
        return pd.NA
    return float(clean.median())


def build_market_view(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate vacancy market view by role, grade, city, and optionally domain."""

    required_cols = ["primary_role", "city_tier"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"expected column {col} for build_market_view")

    grade_col = "grade_final" if "grade_final" in df.columns else "grade"
    if grade_col not in df.columns:
        raise ValueError("expected column grade or grade_final for build_market_view")

    salary_col = "salary_mid_rub_capped"
    if salary_col not in df.columns:
        raise ValueError(f"expected column {salary_col} for build_market_view")

    temp = df.copy()
    group_cols = required_cols.copy() + [grade_col]
    for geo_col in ("country", "region", "city_normalized", "geo_scope"):
        if geo_col in df.columns:
            group_cols.append(geo_col)

    domain_cols = [col for col in df.columns if col.startswith("domain_")]
    if domain_cols:
        temp["domain"] = _derive_domain(df, domain_cols)
        group_cols.append("domain")

    if "is_junior_friendly" in df.columns:
        temp["junior_friendly_flag"] = df["is_junior_friendly"].fillna(False).astype(bool)
    elif "battle_experience" in df.columns:
        temp["junior_friendly_flag"] = (~df["battle_experience"].fillna(False)).astype(bool)
    else:
        temp["junior_friendly_flag"] = pd.NA

    if "is_remote" in df.columns:
        temp["remote_flag"] = df["is_remote"].fillna(False).astype(bool)
    elif "work_mode" in df.columns:
        temp["remote_flag"] = df["work_mode"].fillna("").str.lower().isin(["remote", "hybrid"])
    else:
        temp["remote_flag"] = pd.NA

    if "tech_stack_size" not in df.columns:
        temp["tech_stack_size"] = pd.NA

    salary_metric_col = "_salary_metric_rub"
    temp[salary_metric_col] = pd.to_numeric(df[salary_col], errors="coerce")
    if "salary_disclosed" in df.columns:
        salary_disclosed = df["salary_disclosed"].fillna(False).astype(bool)
        temp[salary_metric_col] = temp[salary_metric_col].where(salary_disclosed)

    aggregations = {
        "vacancy_count_total": (salary_col, "size"),
        "vacancy_count_salary": (salary_metric_col, "count"),
        "salary_median": (salary_metric_col, _median_or_na),
        "salary_q25": (salary_metric_col, lambda s: _quantile_or_na(s, 0.25)),
        "salary_q75": (salary_metric_col, lambda s: _quantile_or_na(s, 0.75)),
        "junior_friendly_share": ("junior_friendly_flag", "mean"),
        "remote_share": ("remote_flag", "mean"),
        "median_tech_stack_size": ("tech_stack_size", _median_or_na),
    }

    summary = temp.groupby(group_cols, observed=True).agg(**aggregations).reset_index()

    summary["vacancy_count"] = summary["vacancy_count_total"]
    summary["sample_size"] = summary["vacancy_count_total"]
    summary["salary_sample_size"] = summary["vacancy_count_salary"]
    summary["salary_coverage_share"] = (
        summary["salary_sample_size"] / summary["sample_size"].where(summary["sample_size"] > 0)
    ).fillna(0.0)
    summary["confidence"] = [
        market_confidence(int(row.sample_size), int(row.salary_sample_size), float(row.salary_coverage_share))
        for row in summary.itertuples(index=False)
    ]

    skill_cols = [col for col in df.columns if col.startswith("skill_") or col.startswith("has_")]
    if skill_cols:
        skill_means = temp[group_cols + skill_cols].copy()
        skill_means[skill_cols] = skill_means[skill_cols].fillna(False).astype(bool)
        formatted = (
            skill_means.groupby(group_cols, observed=True)[skill_cols]
            .mean()
            .apply(_format_top_skills, axis=1)
            .reset_index(name="top_skills")
        )
        summary = summary.merge(formatted, on=group_cols, how="left")

    summary = summary.loc[summary["vacancy_count_total"] > 0]

    return summary.sort_values(by="vacancy_count_total", ascending=False)
