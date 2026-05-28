"""Product-oriented persona utilities for Skillra."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import pandas as pd

from . import config, eda
from .market import market_confidence
from .viz import _format_filters, _humanize_skill_name

MIN_MARKET_N = 80
# Sprint-007 TASK-15: Load noisy skills from YAML config instead of hardcoding
from .config import load_noisy_skills  # noqa: E402 (import after constant)

NOISY_SKILLS = load_noisy_skills()


@dataclass
class Persona:
    """Persona definition for skill-gap and market analysis."""

    name: str
    description: str
    current_skills: List[str]
    target_role: str
    target_grade: str | None = None
    target_city_tier: str | None = None
    target_country: str | None = None
    target_region: str | None = None
    target_city: str | None = None
    target_geo_scope: str | None = None
    target_work_mode: str | None = None
    skill_whitelist: List[str] | None = None
    constraints: Dict[str, object] = field(default_factory=dict)
    goals: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    min_market_n: int = MIN_MARKET_N
    min_market_n: int = MIN_MARKET_N

    # Backward compatibility: expose target_filter as a property to avoid breaking old callers
    @property
    def target_filter(self) -> Dict[str, object]:  # pragma: no cover - legacy shim
        filt: Dict[str, object] = {}
        if self.target_role:
            filt["primary_role"] = self.target_role
        if self.target_grade:
            filt["grade"] = self.target_grade
        if self.target_city_tier:
            filt["city_tier"] = self.target_city_tier
        if self.target_country:
            filt["country"] = self.target_country
        if self.target_region:
            filt["region"] = self.target_region
        if self.target_city:
            filt["city_normalized"] = self.target_city
        if self.target_geo_scope:
            filt["geo_scope"] = self.target_geo_scope
        if self.target_work_mode:
            filt["work_mode"] = self.target_work_mode
        filt.update(self.constraints)
        return filt


__all__ = [
    "Persona",
    "PersonaFilterResult",
    "MIN_MARKET_N",
    "build_skill_demand_profile",
    "skill_gap_for_persona",
    "analyze_persona",
    "plot_persona_skill_gap",
    "DATA_STUDENT",
    "SWITCHER_BI",
    "MID_DATA_ANALYST",
]


@dataclass
class PersonaFilterResult:
    filtered_df: pd.DataFrame
    applied_filters: Dict[str, object]
    filters_used: Dict[str, object]
    relaxed_filters: List[str]
    warnings: List[str]
    grade_column_used: str | None
    min_market_n: int = MIN_MARKET_N

    @property
    def sample_size(self) -> int:
        return len(self.filtered_df)


def _apply_filters(df: pd.DataFrame, filters: Sequence[tuple[str, object]]):
    filtered = df
    applied: Dict[str, object] = {}
    for col, value in filters:
        if col not in filtered.columns:
            continue
        if isinstance(value, (list, tuple, set)):
            filtered = filtered[filtered[col].isin(value)]
        else:
            filtered = filtered[filtered[col] == value]
        applied[col] = value
    return filtered, applied


def _filter_by_target(df: pd.DataFrame, persona: Persona, min_market_n: int | None = None) -> PersonaFilterResult:
    """Filter a dataframe by persona targets and constraints with fallback."""

    threshold = persona.min_market_n if min_market_n is None else min_market_n
    grade_col = "grade_final" if "grade_final" in df.columns else "grade"
    filter_specs: list[tuple[str, object]] = []
    mapping: Mapping[str, Any] = {
        "primary_role": persona.target_role,
        grade_col: persona.target_grade,
        "city_tier": persona.target_city_tier,
        "country": persona.target_country,
        "region": persona.target_region,
        "city_normalized": persona.target_city,
        "geo_scope": persona.target_geo_scope,
        "work_mode": persona.target_work_mode,
    }
    for col, value in mapping.items():
        if value is None:
            continue
        filter_specs.append((col, value))

    for key, value in persona.constraints.items():
        filter_specs.append((key, value))

    active_filters = filter_specs.copy()
    filtered, applied = _apply_filters(df, active_filters)
    relaxed_filters: list[str] = []
    warnings: list[str] = []

    if threshold and filtered.empty:
        warnings.append(f"После применения фильтров сегмент пустой; порог стабильности {threshold} вакансий")

    relax_order: list[str] = list(persona.constraints.keys()) + [
        "geo_scope",
        "city_normalized",
        "region",
        "country",
        "work_mode",
        "city_tier",
        grade_col,
        "primary_role",
    ]

    can_relax = bool(threshold and len(df) >= threshold and len(filtered) < threshold)
    grade_relaxed = False

    for relax_key in relax_order if can_relax else []:
        if len(filtered) >= threshold:
            break
        idx = next((i for i, (col, _) in enumerate(active_filters) if col == relax_key), None)
        if idx is None:
            continue
        active_filters.pop(idx)
        relaxed_filters.append(relax_key)
        if relax_key == grade_col:
            grade_relaxed = True
        filtered, applied = _apply_filters(df, active_filters)

    if threshold and len(filtered) < threshold:
        warnings.append("Сегмент меньше минимального размера " f"(n={len(filtered)}, min_market_n={threshold}).")
    if relaxed_filters:
        warnings.append("Ослаблены фильтры для стабильности: " + ", ".join(relaxed_filters))
    if grade_relaxed:
        warnings.append("Фильтр по целевому грейду ослаблен из-за малого N рынка.")

    return PersonaFilterResult(
        filtered_df=filtered,
        applied_filters=applied,
        filters_used=applied,
        relaxed_filters=relaxed_filters,
        warnings=warnings,
        grade_column_used=grade_col if grade_col in df.columns else None,
        min_market_n=threshold,
    )


def build_skill_demand_profile(
    df: pd.DataFrame,
    persona: Persona,
    skill_prefixes: tuple[str, ...] = ("has_", "skill_"),
    min_share: float = 0.05,
    skill_cols: list[str] | None = None,
    min_market_n: int | None = None,
    filter_result: PersonaFilterResult | None = None,
) -> pd.DataFrame:
    """Compute market demand for skills in the persona's target segment."""

    result = filter_result or _filter_by_target(df, persona, min_market_n=min_market_n)
    df_filtered = result.filtered_df
    if df_filtered.empty:
        return pd.DataFrame(columns=["skill_name", "market_share"])

    resolved_skill_cols = (
        [col for col in skill_cols if col in df_filtered.columns]
        if skill_cols is not None
        else (
            [
                col
                for col in persona.skill_whitelist or []
                if col in df_filtered.columns and col.startswith(skill_prefixes)
            ]
            or [
                c for c in eda.hard_skill_columns(df_filtered) if c.startswith(skill_prefixes) and c not in NOISY_SKILLS
            ]
        )
    )
    if not resolved_skill_cols:
        return pd.DataFrame(columns=["skill_name", "market_share"])
    rows: list[dict[str, object]] = []
    for col in resolved_skill_cols:
        series = df_filtered[col].fillna(False)
        try:
            share = series.astype(bool).mean()
        except Exception:
            continue
        if share < min_share:
            continue
        rows.append({"skill_name": col, "market_share": share})

    demand = pd.DataFrame(rows)
    if demand.empty:
        return demand
    return demand.sort_values(by="market_share", ascending=False).reset_index(drop=True)


def skill_gap_for_persona(
    df: pd.DataFrame,
    persona: Persona,
    skill_cols: List[str] | None = None,
    min_share: float = 0.1,
    top_n: int | None = 20,
    min_market_n: int | None = None,
    filter_result: PersonaFilterResult | None = None,
) -> pd.DataFrame:
    """
    Calculate market share of skills for persona targets and mark gaps.

    Returns columns: skill_name, market_share, persona_has (bool), gap (bool).
    """

    result = filter_result or _filter_by_target(df, persona, min_market_n=min_market_n)
    demand = build_skill_demand_profile(
        df,
        persona,
        skill_prefixes=("has_", "skill_"),
        min_share=min_share,
        skill_cols=skill_cols,
        min_market_n=min_market_n,
        filter_result=result,
    )
    if skill_cols:
        demand = demand[demand["skill_name"].isin(skill_cols)]

    if demand.empty:
        gap_df = pd.DataFrame(columns=["skill_name", "market_share", "persona_has", "gap"])
        gap_df.attrs.update(
            {
                "market_n": result.sample_size,
                "applied_filters": result.applied_filters,
                "filters_used": result.filters_used,
                "relaxed_filters": result.relaxed_filters,
                "warnings": result.warnings,
                "grade_column_used": result.grade_column_used,
                "min_market_n": result.min_market_n,
            }
        )
        return gap_df

    demand["persona_has"] = demand["skill_name"].isin(persona.current_skills)
    demand["gap"] = ~demand["persona_has"] & (demand["market_share"] >= min_share)
    demand_sorted = demand.sort_values(by=["gap", "market_share"], ascending=[False, False])
    if top_n is not None:
        demand_sorted = demand_sorted.head(top_n)
    gap_df = demand_sorted.reset_index(drop=True)
    gap_df.attrs.update(
        {
            "market_n": result.sample_size,
            "applied_filters": result.applied_filters,
            "filters_used": result.filters_used,
            "relaxed_filters": result.relaxed_filters,
            "warnings": result.warnings,
            "grade_column_used": result.grade_column_used,
            "min_market_n": result.min_market_n,
        }
    )
    return gap_df


def analyze_persona(df: pd.DataFrame, persona: Persona, top_k: int = 10) -> dict:
    """Summarize market segment and skill gaps for a persona.

    Returns a dictionary with three core blocks:
    * ``market_summary`` — aggregated metrics for the target segment;
    * ``skill_gap`` — dataframe with market share, persona possession and gap flag;
    * ``recommended_skills`` — ordered list of missing skills to focus on.
    """

    filter_result = _filter_by_target(df, persona, min_market_n=persona.min_market_n)
    df_filtered = filter_result.filtered_df
    vacancy_count = len(df_filtered)
    salary_col = next(
        (col for col in ("salary_mid_rub_capped", "salary_mid_rub", "salary_mid") if col in df_filtered.columns),
        None,
    )
    salary_series = pd.Series(dtype=float)
    if salary_col:
        salary_series = pd.to_numeric(df_filtered[salary_col], errors="coerce")
        if "salary_disclosed" in df_filtered.columns:
            salary_series = salary_series.where(df_filtered["salary_disclosed"].fillna(False).astype(bool))
        salary_series = salary_series.dropna()
    salary_sample_size = int(len(salary_series))
    salary_coverage_share = round(salary_sample_size / vacancy_count, 6) if vacancy_count else None
    confidence = market_confidence(vacancy_count, salary_sample_size, salary_coverage_share)
    warnings = list(filter_result.warnings)
    if confidence == "low":
        warnings.append("Segment confidence is low; salary and demand metrics may be unstable.")

    market_summary: dict[str, object] = {
        "vacancy_count": vacancy_count,
        "sample_size": vacancy_count,
        "salary_sample_size": salary_sample_size,
        "salary_coverage_share": salary_coverage_share,
        "confidence": confidence,
        "min_market_n": filter_result.min_market_n,
    }
    if not salary_series.empty:
        market_summary.update(
            {
                "salary_median": float(salary_series.median()),
                "salary_q25": float(salary_series.quantile(0.25)),
                "salary_q75": float(salary_series.quantile(0.75)),
            }
        )
    if "is_remote" in df_filtered.columns:
        market_summary["remote_share"] = df_filtered["is_remote"].fillna(False).astype(bool).mean()
    if "is_junior_friendly" in df_filtered.columns:
        market_summary["junior_friendly_share"] = df_filtered["is_junior_friendly"].fillna(False).astype(bool).mean()
    if "geo_scope" in df_filtered.columns:
        scopes = df_filtered["geo_scope"].dropna().astype(str)
        unique_scopes = sorted({scope for scope in scopes if scope and scope != "unknown"})
        if len(unique_scopes) == 1:
            market_summary["geo_scope"] = unique_scopes[0]
        elif len(unique_scopes) > 1:
            market_summary["geo_scope"] = "mixed"

    demand_df = build_skill_demand_profile(
        df,
        persona,
        skill_prefixes=("has_", "skill_"),
        min_share=0.05,
        filter_result=filter_result,
    )
    top_demand = demand_df.head(top_k) if not demand_df.empty else pd.DataFrame()

    # Populate top_skills in market_summary from demand profile
    top_skill_names: list[str] = demand_df["skill_name"].head(top_k).tolist() if not demand_df.empty else []
    market_summary["top_skills"] = top_skill_names if top_skill_names else None

    gap_df = skill_gap_for_persona(
        df,
        persona,
        min_share=0.05,
        top_n=top_k,
        filter_result=filter_result,
    )
    recommended_skills: list[str] = gap_df.loc[gap_df["gap"], "skill_name"].head(top_k).tolist()

    return {
        "market_summary": market_summary,
        "skill_gap": gap_df,
        "recommended_skills": recommended_skills,
        "top_skill_demand": top_demand,
        "applied_filters": filter_result.applied_filters,
        "filters_used": filter_result.filters_used,
        "warnings": warnings,
        "grade_column_used": filter_result.grade_column_used,
    }


def plot_persona_skill_gap(
    gap_df: pd.DataFrame,
    persona: Persona,
    output_dir: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Plot top missing skills for a persona and optionally return a Figure."""

    import matplotlib.pyplot as plt

    if gap_df.empty:
        raise ValueError("Gap dataframe is empty; cannot plot skill gaps.")

    missing = gap_df[gap_df["gap"]]
    if missing.empty:
        raise ValueError("Нет недостающих навыков для построения графика")

    top_missing = missing.sort_values(by="market_share", ascending=False)
    fig, ax = plt.subplots(figsize=(10, 6))
    shares_pct = top_missing["market_share"] * 100
    skill_labels = [_humanize_skill_name(raw) for raw in top_missing["skill_name"]]
    bars = ax.barh(skill_labels, shares_pct)
    ax.invert_yaxis()
    ax.set_xlabel("Доля вакансий с навыком, %")

    for bar, share in zip(bars, shares_pct):
        ax.text(
            bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{share:.1f}%",
            va="center",
            fontsize=9,
        )

    market_n = gap_df.attrs.get("market_n")
    relaxed = gap_df.attrs.get("relaxed_filters") or []
    min_market_n = gap_df.attrs.get("min_market_n")
    filters_used = gap_df.attrs.get("filters_used") or gap_df.attrs.get("applied_filters")
    warnings = gap_df.attrs.get("warnings") or []
    subtitle_parts = []
    if market_n is not None:
        subtitle_parts.append(f"N рынка: {market_n}")
    if min_market_n is not None:
        subtitle_parts.append(f"min_n={min_market_n}")
    subtitle_parts.append(_format_filters(filters_used))
    if relaxed:
        subtitle_parts.append("Ослаблены фильтры: " + ", ".join(relaxed))

    ax.set_title(" | ".join(subtitle_parts), fontsize=10)
    fig.suptitle(f"Skill gap для персоны: {persona.name}", fontsize=13, y=0.98)

    if warnings:
        fig.text(
            0.01,
            0.01,
            "Внимание: " + " | ".join(warnings),
            ha="left",
            va="bottom",
            fontsize=9,
            color="darkred",
        )

    output_dir = output_dir or config.FIGURES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"fig_persona_{persona.name.lower().replace(' ', '_')}_skill_gap.png"
    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    fig.savefig(output_path, dpi=200)
    if not return_fig:
        plt.close(fig)
        return output_path
    return fig, output_path


# Pre-defined personas for quick experimentation in the notebook/product layer.
DATA_STUDENT = Persona(
    name="data_student",
    description="Магистрант по данным, целится в Junior DA/DS (фильтруется как data)",
    goals=[
        "Получить первую роль Junior DA/DS",
        "Подтянуть Python/SQL и продуктовую аналитику",
    ],
    limitations=["Неполная занятость из-за учёбы", "Ориентация на remote"],
    current_skills=["skill_sql", "skill_excel", "has_python"],
    target_role="data",
    target_grade="junior",
    target_city_tier=None,
    target_work_mode=None,
    skill_whitelist=[
        "skill_sql",
        "skill_excel",
        "has_python",
        "has_pandas",
        "skill_powerbi",
        "skill_tableau",
        "skill_airflow",
        "has_airflow",
        "skill_dbt",
        "skill_git",
        "has_git",
        "has_spark",
    ],
)

SWITCHER_BI = Persona(
    name="switcher_bi",
    description="Свитчер в продуктовую/BI-аналитику",
    goals=["Перейти из смежной сферы в BI/продуктовую аналитику"],
    limitations=["Нужно быстро выйти на работу", "Ставка на гибрид или офис"],
    current_skills=["skill_excel", "skill_powerbi"],
    target_role="product",
    target_grade="junior",
    target_city_tier=None,
    target_work_mode=None,
    skill_whitelist=[
        "skill_sql",
        "skill_excel",
        "skill_powerbi",
        "skill_tableau",
        "skill_product_metrics",
        "skill_ab_testing",
        "has_python",
        "has_pandas",
        "skill_airflow",
    ],
)

MID_DATA_ANALYST = Persona(
    name="mid_data_analyst",
    description="Middle аналитик, хочет усилить hard-стек",
    goals=["Выйти на позиции middle+", "Усилить ML/продвинутое моделирование"],
    limitations=["Рассматривает офис/гибрид", "Хочет рост зарплаты"],
    current_skills=["skill_sql", "skill_excel", "skill_powerbi"],
    target_role="analyst",
    target_grade="middle",
    target_city_tier=None,
    target_work_mode=None,
    skill_whitelist=[
        "skill_sql",
        "skill_excel",
        "skill_powerbi",
        "skill_tableau",
        "skill_clickhouse",
        "skill_bigquery",
        "skill_ab_testing",
        "skill_product_metrics",
        "has_python",
        "has_pandas",
        "has_numpy",
        "has_sklearn",
        "skill_airflow",
        "has_airflow",
        "has_spark",
    ],
)
