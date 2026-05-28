"""Rule-based career path recommendation model."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from .config import load_noisy_skills

logger = logging.getLogger(__name__)

GRADE_ORDER = {"intern": -1, "jun": 0, "junior": 0, "middle": 1, "mid": 1, "senior": 2, "lead": 3, "principal": 4}

ROLE_ALIASES = {
    "data analyst": {"data", "analyst", "data analyst"},
    "business analyst": {"analyst", "business analyst"},
    "bi analyst": {"analyst", "bi analyst"},
    "data scientist": {"data", "ml", "data scientist"},
    "ml engineer": {"ml", "ml engineer"},
}


@dataclass
class CareerNode:
    """Aggregated market node for one role and grade."""

    role: str
    grade: str
    salary_p50: Optional[float]
    vacancy_count: int
    top_skills: list[str] = field(default_factory=list)


@dataclass
class CareerTransition:
    """Recommended progression between two adjacent market nodes."""

    from_node: CareerNode
    to_node: CareerNode
    skills_to_add: list[str]
    salary_delta_pct: Optional[float]
    demand_trend: str


def _normalize_label(value: Any) -> str:
    return str(value).strip().lower().replace("_", " ")


def _grade_rank(grade: Any) -> int:
    return GRADE_ORDER.get(_normalize_label(grade), 10_000)


def _grade_column(df: pd.DataFrame) -> str:
    if "grade_final" in df.columns:
        return "grade_final"
    if "grade" in df.columns:
        return "grade"
    raise ValueError("expected column grade or grade_final for career path")


def _salary_column(df: pd.DataFrame) -> str:
    for column in ("salary_mid_rub_capped", "salary_mid_rub", "salary_mid"):
        if column in df.columns:
            return column
    raise ValueError("expected salary_mid_rub_capped, salary_mid_rub, or salary_mid for career path")


def _clean_skill_name(column: str) -> str:
    normalized = column.strip().lower()
    for prefix in ("skill_", "has_"):
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix)
    return normalized


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


def _role_mask(df: pd.DataFrame, role: str) -> pd.Series:
    if "primary_role" not in df.columns:
        raise ValueError("expected column primary_role for career path")

    requested = _normalize_label(role)
    candidates = ROLE_ALIASES.get(requested, {requested})
    normalized_roles = df["primary_role"].fillna("").map(_normalize_label)
    mask = normalized_roles.isin(candidates)
    if mask.any():
        return mask

    return normalized_roles.apply(lambda value: requested in value or value in requested)


def _top_skills(df: pd.DataFrame, skill_cols: list[str], top_n: int = 10) -> list[str]:
    if df.empty or not skill_cols:
        return []

    counts_by_skill: dict[str, int] = {}
    for column in skill_cols:
        skill_name = _clean_skill_name(column)
        count = int(df[column].fillna(False).astype(bool).sum())
        if count > counts_by_skill.get(skill_name, 0):
            counts_by_skill[skill_name] = count

    ranked = sorted(counts_by_skill.items(), key=lambda item: (-item[1], item[0]))
    return [skill for skill, count in ranked[:top_n] if count > 0]


def _build_nodes(features_df: pd.DataFrame, role: str) -> list[CareerNode]:
    if features_df.empty:
        return []

    grade_col = _grade_column(features_df)
    salary_col = _salary_column(features_df)
    skill_cols = _skill_columns(features_df)
    role_df = features_df.loc[_role_mask(features_df, role)].copy()
    if role_df.empty:
        return []

    nodes: list[CareerNode] = []
    for grade, grade_df in role_df.groupby(grade_col, observed=True, sort=False):
        grade_name = str(grade)
        if _grade_rank(grade_name) == 10_000:
            continue
        salary = pd.to_numeric(grade_df[salary_col], errors="coerce").dropna()
        salary_p50 = float(salary.median()) if not salary.empty else None
        nodes.append(
            CareerNode(
                role=role,
                grade=grade_name,
                salary_p50=salary_p50,
                vacancy_count=int(len(grade_df)),
                top_skills=_top_skills(grade_df, skill_cols),
            )
        )

    return sorted(nodes, key=lambda node: (_grade_rank(node.grade), node.grade))


def _salary_delta_pct(from_salary: float | None, to_salary: float | None) -> float | None:
    if from_salary is None or to_salary is None or from_salary <= 0:
        return None
    return float((to_salary - from_salary) / from_salary * 100)


def _demand_trend(history_df: pd.DataFrame | None, role: str, grade: str, weeks: int = 12) -> str:
    if history_df is None or history_df.empty or "vacancy_count" not in history_df.columns:
        return "stable"

    filtered = history_df.copy()
    if "role" in filtered.columns:
        requested_role = _normalize_label(role)
        role_candidates = ROLE_ALIASES.get(requested_role, {requested_role})
        filtered = filtered[filtered["role"].map(_normalize_label).isin(role_candidates)]
    if "grade" in filtered.columns:
        requested_grade = _normalize_label(grade)
        filtered = filtered[filtered["grade"].map(_normalize_label) == requested_grade]
    if filtered.empty:
        return "stable"

    trend = filtered.groupby("week_start", as_index=False, observed=True)["vacancy_count"].sum()
    trend["_week_sort"] = pd.to_datetime(trend["week_start"], errors="coerce")
    trend = trend.sort_values("_week_sort").tail(weeks)
    if len(trend) < 2:
        return "stable"

    first = float(trend["vacancy_count"].iloc[0])
    last = float(trend["vacancy_count"].iloc[-1])
    if first <= 0:
        return "growing" if last > 0 else "stable"

    delta = (last - first) / first
    if delta > 0.05:
        return "growing"
    if delta < -0.05:
        return "declining"
    return "stable"


def build_career_graph(features_df: pd.DataFrame, role: str) -> list[CareerTransition]:
    """Build a grade progression graph for the given role."""

    nodes = _build_nodes(features_df, role)
    transitions: list[CareerTransition] = []
    for from_node, to_node in zip(nodes, nodes[1:]):
        skills_to_add = [skill for skill in to_node.top_skills if skill not in set(from_node.top_skills)]
        transitions.append(
            CareerTransition(
                from_node=from_node,
                to_node=to_node,
                skills_to_add=skills_to_add[:5],
                salary_delta_pct=_salary_delta_pct(from_node.salary_p50, to_node.salary_p50),
                demand_trend="stable",
            )
        )

    logger.info("Built career graph role=%s transitions=%d", role, len(transitions))
    return transitions


def recommend_next_step(
    current_role: str,
    current_grade: str,
    user_skills: list[str],
    features_df: pd.DataFrame,
    history_df: pd.DataFrame | None = None,
) -> dict:
    """Return a serializable career recommendation for the next grade step."""

    nodes = _build_nodes(features_df, current_role)
    current_grade_key = _normalize_label(current_grade)
    user_skill_set = {_clean_skill_name(skill) for skill in user_skills}
    current_node = next((node for node in nodes if _normalize_label(node.grade) == current_grade_key), None)

    next_node: CareerNode | None = None
    if current_node is not None:
        for candidate in nodes:
            if _grade_rank(candidate.grade) > _grade_rank(current_node.grade):
                next_node = candidate
                break
    else:
        current_rank = _grade_rank(current_grade)
        next_node = next((node for node in nodes if _grade_rank(node.grade) > current_rank), None)

    if next_node is None:
        return {
            "current_role": current_role,
            "current_grade": current_grade,
            "next_grade": None,
            "salary_current_p50": current_node.salary_p50 if current_node else None,
            "salary_next_p50": None,
            "salary_delta_pct": None,
            "skills_to_add": [],
            "demand_trend": "stable",
            "vacancy_count_current": current_node.vacancy_count if current_node else 0,
            "vacancy_count_next": 0,
        }

    from_top_skills = set(current_node.top_skills) if current_node else set()
    skills_to_add = [
        skill
        for skill in next_node.top_skills
        if skill not in from_top_skills and _clean_skill_name(skill) not in user_skill_set
    ][:5]
    salary_current = current_node.salary_p50 if current_node else None
    demand_trend = _demand_trend(history_df, current_role, next_node.grade)

    return {
        "current_role": current_role,
        "current_grade": current_grade,
        "next_grade": next_node.grade,
        "salary_current_p50": salary_current,
        "salary_next_p50": next_node.salary_p50,
        "salary_delta_pct": _salary_delta_pct(salary_current, next_node.salary_p50),
        "skills_to_add": skills_to_add,
        "demand_trend": demand_trend,
        "vacancy_count_current": current_node.vacancy_count if current_node else 0,
        "vacancy_count_next": next_node.vacancy_count,
    }
