"""EDA helper functions."""
from __future__ import annotations

from typing import Iterable, List

import pandas as pd


def missing_share(df: pd.DataFrame, top_n: int = 20) -> pd.Series:
    """Return top missing shares."""
    return df.isna().mean().sort_values(ascending=False).head(top_n)


def hard_skill_columns(df: pd.DataFrame) -> list[str]:
    """Return hard skill columns combining skill_* and relevant has_* flags."""

    skill_cols = [col for col in df.columns if col.startswith("skill_")]
    has_cols = [col for col in df.columns if col.startswith("has_")]

    excluded = {
        "has_metro",
        "has_test_task",
        "has_mentoring",
    }
    has_skill_cols = [col for col in has_cols if col not in excluded]

    return sorted(set(skill_cols + has_skill_cols))


def describe_salary_by_group(
    df: pd.DataFrame, group_col: str, salary_col: str = "salary_mid_rub_capped", top_n: int | None = None
) -> pd.DataFrame:
    """Summaries of salary by categorical grouping."""
    grouped = (
        df.groupby(group_col)[salary_col]
        .agg(["count", "median", "mean", "min", "max"])
        .rename(columns={"count": "n"})
        .sort_values(by="median", ascending=False)
    )
    if top_n:
        grouped = grouped.head(top_n)
    return grouped.reset_index()


def describe_salary_two_dim(
    df: pd.DataFrame,
    group_a: str,
    group_b: str,
    salary_col: str = "salary_mid_rub_capped",
    agg: str = "median",
) -> pd.DataFrame:
    """Pivot salary statistics across two categorical dimensions."""
    return df.pivot_table(values=salary_col, index=group_a, columns=group_b, aggfunc=agg)


def salary_summary_by_category(
    df: pd.DataFrame,
    category_col: str,
    salary_col: str = "salary_mid_rub_capped",
) -> pd.DataFrame:
    """Summarize salary by a categorical column with count/median/mean/std."""

    if category_col not in df.columns:
        raise ValueError(f"expected column {category_col} for salary_summary_by_category")
    return (
        df.groupby(category_col, observed=False)[salary_col]
        .agg(n="count", median="median", mean="mean", std="std")
        .reset_index()
        .sort_values(by="median", ascending=False)
    )


def salary_by_city_tier(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    return salary_summary_by_category(df, "city_tier", salary_col)


def salary_by_grade(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    return salary_summary_by_category(df, "grade", salary_col)


def salary_by_primary_role(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    return salary_summary_by_category(df, "primary_role", salary_col)


def salary_by_experience_bucket(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    base = None
    if "exp_min_years" in df.columns:
        base = df["exp_min_years"].copy()
        if "exp_max_years" in df.columns:
            base = base.fillna(df["exp_max_years"])
    elif "exp_max_years" in df.columns:
        base = df["exp_max_years"]
    if base is None:
        raise ValueError("expected exp_min_years or exp_max_years for salary_by_experience_bucket")

    buckets = pd.cut(base.fillna(-1), bins=[-1, 1, 3, 6, 100], labels=["0-1", "1-3", "3-6", "6+"], include_lowest=True)
    temp = df.copy()
    temp["exp_bucket"] = buckets
    return salary_summary_by_category(temp, "exp_bucket", salary_col)


def salary_by_english_level(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    return salary_summary_by_category(df, "lang_english_level", salary_col)


GRADE_ORDER = ["intern", "junior", "junior+", "middle", "senior", "lead", "architect", "unknown"]
ENGLISH_LEVEL_ORDER = ["no_english", "a2", "b1", "b2", "c1_plus", "unknown"]

CATEGORY_ORDER: dict[str, list[str]] = {
    "grade": GRADE_ORDER,
    "grade_final": GRADE_ORDER,
    "grade_from_experience": GRADE_ORDER,
    "lang_english_level": ENGLISH_LEVEL_ORDER,
}


def sort_categories(df: pd.DataFrame, cols: Iterable[str] | None = None) -> pd.DataFrame:
    """Return a copy with selected categorical columns ordered consistently."""

    result = df.copy()
    target_cols = CATEGORY_ORDER.keys() if cols is None else cols

    for col in target_cols:
        if col not in result.columns:
            continue

        order = CATEGORY_ORDER.get(col)
        if not order:
            continue

        result[col] = pd.Categorical(result[col], categories=order, ordered=True)

    return result


def _normalize_english_level(level: str | None, required: bool | None) -> str:
    """Map raw English requirement markers to a standard bucket."""

    if required is False:
        return "no_english"

    if not level or pd.isna(level):
        return "unknown"

    level_normalized = str(level).strip().lower()
    mapping = {
        "none": "no_english",
        "no": "no_english",
        "basic": "a2",
        "a2": "a2",
        "elementary": "a2",
        "pre-intermediate": "a2",
        "intermediate": "b1",
        "b1": "b1",
        "upper_intermediate": "b2",
        "upper-intermediate": "b2",
        "upper intermediate": "b2",
        "b2": "b2",
        "advanced": "c1_plus",
        "fluent": "c1_plus",
        "c1": "c1_plus",
        "c2": "c1_plus",
        "native": "c1_plus",
        "proficient": "c1_plus",
    }

    return mapping.get(level_normalized, "unknown")


def english_requirement_stats(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    """Bucket English requirements and summarize vacancy counts/share/salary."""

    lang_cols = [col for col in df.columns if col.startswith("lang_")]
    if not lang_cols:
        raise KeyError("english_requirement_stats: expected lang_* columns")
    if salary_col not in df.columns:
        raise KeyError(f"english_requirement_stats: expected column {salary_col}")

    required = df.get("lang_english_required")
    level = df.get("lang_english_level")
    temp = df.copy()
    temp["english_level"] = [
        _normalize_english_level(lvl, req)
        for lvl, req in zip(
            level if level is not None else [None] * len(df),
            required if required is not None else [None] * len(df),
        )
    ]

    grouped = (
        temp.groupby("english_level")[salary_col]
        .agg(
            vacancy_count="count",
            salary_median="median",
            salary_q25=lambda s: s.quantile(0.25),
            salary_q75=lambda s: s.quantile(0.75),
        )
        .reset_index()
    )
    total = len(temp)
    grouped["share"] = grouped["vacancy_count"] / total if total else 0
    grouped["english_level"] = pd.Categorical(
        grouped["english_level"], categories=ENGLISH_LEVEL_ORDER, ordered=True
    )
    grouped = grouped.sort_values(by="english_level")
    return grouped.reset_index(drop=True)


def salary_by_stack_size(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    bins: list[int] | None = None,
) -> pd.DataFrame:
    if bins is None:
        bins = [0, 3, 6, 10, 100]

    if "tech_stack_size" not in df.columns:
        raise ValueError("expected tech_stack_size for salary_by_stack_size")

    labels = [f"{bins[i]}-{bins[i+1]}" if i < len(bins) - 2 else f">={bins[i]}" for i in range(len(bins) - 1)]
    temp = df.copy()
    temp["tech_stack_bin"] = pd.cut(temp["tech_stack_size"], bins=bins, labels=labels, include_lowest=True, right=False)
    return salary_summary_by_category(temp, "tech_stack_bin", salary_col)


def extract_primary_domain(row: pd.Series, domain_cols: list[str], priorities: list[str] | None = None) -> str:
    """Return the primary domain flag for a vacancy row.

    Args:
        row: A row containing boolean ``domain_*`` columns.
        domain_cols: List of column names to inspect.
        priorities: Optional list of domain names (without ``domain_`` prefix)
            to check first when multiple flags are True.

    Returns:
        The domain name without the ``domain_`` prefix, or ``"unknown"`` if no
        flags are set.
    """

    available_cols = [col for col in domain_cols if col in row.index]
    if not available_cols:
        return "unknown"

    flags = row[available_cols].fillna(False).astype(bool)

    ordered_cols = available_cols
    if priorities:
        domain_to_col = {col.removeprefix("domain_"): col for col in available_cols}
        priority_cols = [domain_to_col[dom] for dom in priorities if dom in domain_to_col]
        remaining_cols = [col for col in available_cols if col not in priority_cols]
        ordered_cols = priority_cols + remaining_cols

    for col in ordered_cols:
        if bool(flags[col]):
            return col.removeprefix("domain_")

    return "unknown"


def describe_salary_by_domain(
    df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped", priorities: list[str] | None = None
) -> pd.DataFrame:
    """Summarize salary metrics by primary domain derived from domain_* columns."""

    if salary_col not in df.columns:
        raise ValueError(f"expected column {salary_col} for describe_salary_by_domain")

    domain_cols = sorted([col for col in df.columns if col.startswith("domain_")])
    if not domain_cols:
        return pd.DataFrame()

    domain_flags = df[domain_cols].fillna(False).astype(bool)
    temp = df.copy()
    temp["domain"] = domain_flags.apply(extract_primary_domain, axis=1, args=(domain_cols, priorities))

    grouped = (
        temp.groupby("domain")[salary_col]
        .agg(
            vacancy_count="count",
            salary_median="median",
            salary_q25=lambda s: s.quantile(0.25),
            salary_q75=lambda s: s.quantile(0.75),
        )
        .reset_index()
    )
    total = len(temp)
    grouped["share"] = grouped["vacancy_count"] / total if total else 0
    return grouped.sort_values(by="vacancy_count", ascending=False)


def correlation_matrix(df: pd.DataFrame, cols: Iterable[str] | None = None) -> pd.DataFrame:
    """Compute Pearson correlation matrix for numeric columns."""
    if cols is None:
        numeric_df = df.select_dtypes(include=["number"])
    else:
        numeric_df = df[list(cols)]
    return numeric_df.corr()


def top_value_counts(df: pd.DataFrame, col: str, top_n: int = 15) -> pd.Series:
    """Return top frequency counts for a categorical column."""
    return df[col].value_counts().head(top_n)


def skill_frequency(df: pd.DataFrame, skill_cols: Iterable[str] | None = None, top_n: int = 15) -> pd.Series:
    """Return aggregated frequencies for provided (or inferred) skill columns."""
    resolved_skills = hard_skill_columns(df) if skill_cols is None else list(skill_cols)
    present = [col for col in resolved_skills if col in df.columns]
    if not present:
        return pd.Series(dtype="float64")
    freq = df[present].mean().sort_values(ascending=False)
    return freq.head(top_n)


def skill_share_by_grade(
    df: pd.DataFrame,
    skill_cols: list[str] | None = None,
    grade_col: str = "grade",
) -> pd.DataFrame:
    """Compute share of vacancies with each skill across grades."""

    if grade_col not in df.columns:
        raise ValueError("expected grade column for skill_share_by_grade")

    resolved_skills = hard_skill_columns(df) if skill_cols is None else list(skill_cols)
    available = [col for col in resolved_skills if col in df.columns]
    if not available:
        return pd.DataFrame()

    subset = df[[grade_col] + available].copy()
    subset[available] = subset[available].fillna(False).astype(bool)
    pivot = subset.groupby(grade_col)[available].mean().T
    pivot.index.name = "skill"
    return pivot


def junior_friendly_share(df: pd.DataFrame, group_col: str = "primary_role") -> pd.DataFrame:
    """Share of junior-friendly and battle-experience flags by the requested category."""

    if group_col not in df.columns:
        raise ValueError(f"expected column {group_col} for junior_friendly_share")

    target_flags = [col for col in ["is_junior_friendly", "battle_experience"] if col in df.columns]
    if not target_flags:
        raise ValueError("expected is_junior_friendly or battle_experience columns for junior_friendly_share")

    subset = df[[group_col] + target_flags].copy()
    subset[target_flags] = subset[target_flags].fillna(False).astype(bool)
    grouped = subset.groupby(group_col, observed=False)[target_flags].mean().reset_index()
    return grouped


def salary_summary_by_grade_and_city(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    """Median and quartiles of salary by grade and city tier."""

    required = {"grade", "city_tier"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Ожидал колонки {missing} для salary_summary_by_grade_and_city")

    summary = (
        df.groupby(["grade", "city_tier"])[salary_col]
        .agg(count="count", median="median", q1=lambda s: s.quantile(0.25), q3=lambda s: s.quantile(0.75))
        .reset_index()
    )
    return summary


def salary_summary_by_role_and_work_mode(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    """Median salary by primary role and work mode."""

    required = {"primary_role", "work_mode"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Ожидал колонки {missing} для salary_summary_by_role_and_work_mode")

    return (
        df.groupby(["primary_role", "work_mode"], observed=True)[salary_col]
        .median()
        .reset_index()
        .rename(columns={salary_col: "salary_median"})
    )


def remote_share_by_role(df: pd.DataFrame) -> pd.DataFrame:
    """Share of remote positions per primary role."""

    required = {"primary_role", "is_remote"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Ожидал колонки {missing} для remote_share_by_role")

    pivot = df.groupby("primary_role", observed=True)[["is_remote"]].mean().reset_index()
    pivot = pivot.rename(columns={"is_remote": "remote_share"})
    return pivot.sort_values(by="remote_share", ascending=False)


def benefits_summary_by_company(
    df: pd.DataFrame, company_col: str = "company", top_n: int = 10
) -> pd.DataFrame:
    """Average benefits per vacancy and per-benefit shares for top employers."""

    benefits = [col for col in df.columns if col.startswith("benefit_")]
    if not benefits or company_col not in df.columns:
        return pd.DataFrame()

    top_companies = df[company_col].value_counts().head(top_n).index
    subset = df[df[company_col].isin(top_companies)].copy()
    subset[benefits] = subset[benefits].fillna(False).astype(bool)
    subset["benefits_count_row"] = subset[benefits].astype(int).sum(axis=1)
    agg = subset.groupby(company_col)[benefits + ["benefits_count_row"]].mean()
    agg = agg.rename(columns={"benefits_count_row": "benefits_per_vacancy"})
    agg["n_vacancies"] = subset.groupby(company_col).size()
    return agg.reset_index()


def benefits_summary_by_grade(df: pd.DataFrame) -> pd.DataFrame:
    """Benefit availability by grade."""

    benefits = [col for col in df.columns if col.startswith("benefit_")]
    if not benefits or "grade" not in df.columns:
        return pd.DataFrame()

    subset = df.copy()
    subset[benefits] = subset[benefits].fillna(False).astype(bool)
    subset["benefits_count_row"] = subset[benefits].astype(int).sum(axis=1)
    agg = subset.groupby("grade")[benefits + ["benefits_count_row"]].mean()
    agg = agg.rename(columns={"benefits_count_row": "benefits_per_vacancy"})
    agg["n_vacancies"] = subset.groupby("grade").size()
    return agg.reset_index()


def soft_skills_overall_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Overall share and counts for soft skill flags."""

    soft_cols = [col for col in df.columns if col.startswith("soft_")]
    if not soft_cols:
        return pd.DataFrame()

    subset = df[soft_cols].fillna(False).astype(bool)
    result = pd.DataFrame({
        "count": subset.sum(),
        "share": subset.mean(),
    })
    result.index.name = "soft_skill"
    return result.reset_index()


def top_employers(
    df: pd.DataFrame,
    company_col: str = "company",
    salary_col: str = "salary_mid_rub_capped",
    rating_col: str | None = "employer_rating",
    top_n: int = 15,
) -> pd.DataFrame:
    """Return top employers by vacancy count with optional salary and rating stats."""

    if company_col not in df.columns:
        return pd.DataFrame()

    top_companies = df[company_col].value_counts().head(top_n).index
    subset = df[df[company_col].isin(top_companies)].copy()

    agg_spec: dict[str, tuple[str, str]] = {"vacancy_count": (company_col, "size")}
    if salary_col in subset.columns:
        agg_spec["salary_median"] = (salary_col, "median")
    if rating_col and rating_col in subset.columns:
        agg_spec["rating_mean"] = (rating_col, "mean")

    summary = subset.groupby(company_col).agg(**agg_spec).reset_index()
    summary["share"] = summary["vacancy_count"] / len(df) if len(df) else 0
    return summary.sort_values(by="vacancy_count", ascending=False)


def benefits_by_employer(df: pd.DataFrame, company_col: str = "company", top_n: int = 10) -> pd.DataFrame:
    """Share of benefits for the top employers."""

    benefits = [col for col in df.columns if col.startswith("benefit_")]
    if not benefits or company_col not in df.columns:
        return pd.DataFrame()

    top_companies = df[company_col].value_counts().head(top_n).index
    subset = df[df[company_col].isin(top_companies)].copy()
    subset[benefits] = subset[benefits].fillna(False).astype(bool)

    grouped = subset.groupby(company_col)[benefits].mean()
    grouped["n_vacancies"] = subset.groupby(company_col).size()
    return grouped.reset_index()


def soft_skills_by_employer(df: pd.DataFrame, company_col: str = "company", top_n: int = 10) -> pd.DataFrame:
    """Soft skill shares for top employers."""

    soft_cols = [col for col in df.columns if col.startswith("soft_")]
    if not soft_cols or company_col not in df.columns:
        return pd.DataFrame()

    top_companies = df[company_col].value_counts().head(top_n).index
    subset = df[df[company_col].isin(top_companies)].copy()
    subset[soft_cols] = subset[soft_cols].fillna(False).astype(bool)
    agg = subset.groupby(company_col)[soft_cols].mean()
    agg["n_vacancies"] = subset.groupby(company_col).size()
    return agg.reset_index()


def soft_skills_correlation(df: pd.DataFrame) -> pd.DataFrame:
    """Correlation matrix for soft skills only."""

    soft_cols = [col for col in df.columns if col.startswith("soft_")]
    if not soft_cols:
        return pd.DataFrame()
    subset = df[soft_cols].fillna(False).astype(float)
    return subset.corr()


def junior_friendly_share_by_segment(df: pd.DataFrame) -> pd.DataFrame:
    """Share of junior-friendly flags by primary role and grade."""

    flags = ["is_for_juniors", "allows_students", "has_mentoring", "has_test_task"]
    missing_cols = [col for col in flags if col not in df.columns]
    if missing_cols:
        raise KeyError(
            f"Ожидал колонки {missing_cols} для junior_friendly_share_by_segment"
        )

    group_cols = [col for col in ["primary_role", "grade"] if col in df.columns]
    melted = df[group_cols + flags].melt(id_vars=group_cols, value_vars=flags, var_name="flag", value_name="value")
    result = (
        melted.groupby(group_cols + ["flag"])["value"].mean().reset_index().rename(columns={"value": "share"})
    )
    return result


def _normalize_education_level(level: str | None, required: bool | None, technical: bool | None) -> str:
    """Map education markers to coarse buckets."""

    if level:
        level = str(level).strip().lower()

    if level == "master_or_higher":
        return "master_phd"

    if technical:
        return "technical_only"

    if required or level in {"any_he", "bachelor_or_higher", "partial_higher"}:
        return "any_degree"

    return "no_degree_required"


def education_requirement_stats(df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped") -> pd.DataFrame:
    """Bucket education requirements with counts, share and salary medians."""

    edu_cols = [col for col in df.columns if col.startswith("edu_")]
    if not edu_cols:
        raise KeyError("education_requirement_stats: expected edu_* columns")
    if salary_col not in df.columns:
        raise KeyError(f"education_requirement_stats: expected column {salary_col}")

    required = df.get("edu_required")
    level = df.get("edu_level")
    technical = df.get("edu_technical")
    temp = df.copy()
    temp["education_level"] = [
        _normalize_education_level(lvl, req, tech)
        for lvl, req, tech in zip(
            level if level is not None else [None] * len(df),
            required if required is not None else [None] * len(df),
            technical if technical is not None else [None] * len(df),
        )
    ]

    grouped = (
        temp.groupby("education_level")[salary_col]
        .agg(
            vacancy_count="count",
            salary_median="median",
            salary_q25=lambda s: s.quantile(0.25),
            salary_q75=lambda s: s.quantile(0.75),
        )
        .reset_index()
    )
    total = len(temp)
    grouped["share"] = grouped["vacancy_count"] / total if total else 0
    return grouped.sort_values(by="vacancy_count", ascending=False)


__all__ = [
    "GRADE_ORDER",
    "ENGLISH_LEVEL_ORDER",
    "CATEGORY_ORDER",
    "sort_categories",
    "missing_share",
    "describe_salary_by_group",
    "describe_salary_two_dim",
    "salary_summary_by_category",
    "extract_primary_domain",
    "describe_salary_by_domain",
    "salary_by_city_tier",
    "salary_by_grade",
    "salary_by_primary_role",
    "salary_by_experience_bucket",
    "salary_by_english_level",
    "english_requirement_stats",
    "salary_by_stack_size",
    "education_requirement_stats",
    "correlation_matrix",
    "top_value_counts",
    "skill_frequency",
    "skill_share_by_grade",
    "junior_friendly_share",
    "salary_summary_by_grade_and_city",
    "salary_summary_by_role_and_work_mode",
    "remote_share_by_role",
    "benefits_summary_by_company",
    "benefits_summary_by_grade",
    "soft_skills_overall_stats",
    "soft_skills_by_employer",
    "soft_skills_correlation",
    "junior_friendly_share_by_segment",
    "top_employers",
    "benefits_by_employer",
]
