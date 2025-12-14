"""Visualization utilities for reports."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import matplotlib.pyplot as plt
import pandas as pd

from .config import FIGURES_DIR, ensure_directories
from . import eda as eda_mod


ensure_directories()

BAR_FIGSIZE = (10, 6)
HEATMAP_FIGSIZE = (10, 7)
GRADE_ORDER = ["intern", "junior", "junior+", "middle", "senior", "lead", "architect", "unknown"]
ROLE_ORDER = [
    "backend",
    "frontend",
    "fullstack",
    "mobile",
    "qa",
    "devops",
    "analyst",
    "data",
    "ml",
    "product",
    "manager",
    "other",
    "unknown",
]
ENGLISH_ORDER = ["no_english", "a2", "b1", "b2", "c1_plus", "unknown"]
WORK_MODE_ORDER = ["office", "hybrid", "remote", "field", "unknown"]


def _ordered_categories(categories: Iterable[str], order: Sequence[str]) -> list[str]:
    deduped = []
    for cat in categories:
        cat_str = str(cat)
        if cat_str not in deduped:
            deduped.append(cat_str)

    unknown_present = "unknown" in deduped
    without_unknown = [cat for cat in deduped if cat != "unknown"]

    ordered = [cat for cat in order if cat in without_unknown]
    remaining = [cat for cat in without_unknown if cat not in ordered]
    result = ordered + remaining

    if unknown_present:
        result.append("unknown")

    return result


def _save_fig(fig: plt.Figure, filename: str | Path, close: bool = True) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    filename_path = Path(filename)
    output = filename_path if filename_path.is_absolute() else FIGURES_DIR / filename_path
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    if close:
        plt.close(fig)
    return output


def _humanize_skill_name(raw: str) -> str:
    name = raw
    for prefix in ("skill_", "has_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    words = name.split("_")
    mapping = {
        "sql": "SQL",
        "python": "Python",
        "excel": "Excel",
        "powerbi": "Power BI",
        "ml": "ML",
        "ai": "AI",
        "qa": "QA",
    }
    processed = [mapping.get(w.lower(), w.capitalize() if len(w) > 3 else w.upper()) for w in words]
    return " ".join(processed)


def _format_filters(filters_used: dict[str, object] | None) -> str:
    if not filters_used:
        return "Фильтры: нет"
    parts = []
    for key, value in filters_used.items():
        if isinstance(value, (list, tuple, set)):
            rendered = ", ".join(map(str, value))
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return "Фильтры: " + "; ".join(parts)


def _finalize_figure(fig: plt.Figure, filename: str | Path, return_fig: bool = False):
    path = _save_fig(fig, filename, close=not return_fig)
    if return_fig:
        return fig, path
    return path


def _require_columns(df: pd.DataFrame, cols: Iterable[str], func_name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{func_name}: expected columns {missing}, but they are missing")


def salary_by_grade_box(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    grade_col: str = "grade_final",
    return_fig: bool = False,
):
    _require_columns(df, [grade_col, salary_col], "salary_by_grade_box")
    df_local = df.copy()
    df_local[grade_col] = pd.Categorical(
        df_local[grade_col],
        categories=_ordered_categories(df_local[grade_col].unique(), GRADE_ORDER),
        ordered=True,
    )
    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    df_local.boxplot(column=salary_col, by=grade_col, ax=ax)
    ax.set_title("Зарплаты по грейдам")
    ax.set_xlabel("Грейд")
    ax.set_ylabel("Зарплата (RUB, с каппингом)")
    fig.suptitle("")
    return _finalize_figure(fig, "fig_salary_by_grade_box.png", return_fig)


def salary_by_role_box(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    top_n: int = 8,
    roles: list[str] | None = None,
    exclude_roles: tuple[str, ...] = ("other",),
    return_fig: bool = False,
):
    _require_columns(df, ["primary_role", salary_col], "salary_by_role_box")
    df_local = df[~df["primary_role"].isin(exclude_roles)].copy()

    if roles is not None:
        ordered_roles = _ordered_categories(roles, ROLE_ORDER)
        categories = [role for role in ordered_roles if role in df_local["primary_role"].unique()]
    else:
        top_roles = df_local["primary_role"].value_counts().head(top_n).index
        categories = _ordered_categories(top_roles, ROLE_ORDER)

    if not categories:
        raise ValueError("salary_by_role_box: no roles available after filtering")

    filtered = df_local[df_local["primary_role"].isin(categories)].copy()
    filtered["primary_role"] = pd.Categorical(filtered["primary_role"], categories=categories, ordered=True)
    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    filtered.boxplot(column=salary_col, by="primary_role", ax=ax, rot=45)
    ax.set_title("Зарплаты по ключевым ролям")
    ax.set_xlabel("Роль")
    ax.set_ylabel("Зарплата (RUB, с каппингом)")
    fig.suptitle("")
    return _finalize_figure(fig, "fig_salary_by_role_box.png", return_fig)


def salary_by_role_flags_box(
    df: pd.DataFrame,
    roles: list[str],
    salary_col: str = "salary_mid_rub_capped",
    role_prefix: str = "role_",
    output_path: str | Path = "fig_salary_by_role_flags_box.png",
    title: str = "Зарплаты по ключевым ролям (multi-label)",
    return_fig: bool = False,
):
    if not roles:
        raise ValueError("salary_by_role_flags_box: roles list cannot be empty")

    role_columns = [f"{role_prefix}{role}" for role in roles]
    _require_columns(df, role_columns + [salary_col], "salary_by_role_flags_box")

    ordered_roles = _ordered_categories(roles, ROLE_ORDER)
    data: list[pd.Series] = []
    labels: list[str] = []
    excluded: list[tuple[str, int, int]] = []

    for role in ordered_roles:
        role_col = f"{role_prefix}{role}"
        mask_role = df[role_col].fillna(False).astype(bool)
        n_total = int(mask_role.sum())
        salary_mask = mask_role & df[salary_col].notna()
        n_salary = int(salary_mask.sum())

        if n_salary == 0:
            excluded.append((role, n_total, n_salary))
            continue

        role_label = role.upper() if len(role) <= 3 else role.capitalize()
        data.append(df.loc[salary_mask, salary_col])
        labels.append(f"{role_label} (N={n_salary})")

    if not data:
        raise ValueError("salary_by_role_flags_box: no roles with salary data available")

    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    ax.boxplot(data, labels=labels)
    ax.set_title(title)
    ax.set_xlabel("Роль")
    ax.set_ylabel("Зарплата (RUB, с каппингом)")
    fig.suptitle("")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    if excluded:
        footnote_parts = [f"{role} (N_total={n_total}, N_salary={n_salary})" for role, n_total, n_salary in excluded]
        fig.subplots_adjust(bottom=0.2)
        fig.text(
            0.01,
            0.01,
            "Исключены из графика: " + "; ".join(footnote_parts),
            ha="left",
            va="bottom",
            fontsize=8,
        )

    return _finalize_figure(fig, output_path, return_fig)


def salary_by_grade_city_heatmap(
    summary_df: pd.DataFrame, value_col: str = "median", return_fig: bool = False
):
    """Heatmap of salary metric by grade (rows) and city tier (columns)."""

    _require_columns(summary_df, ["grade", "city_tier", value_col], "salary_by_grade_city_heatmap")
    pivot = summary_df.pivot(index="grade", columns="city_tier", values=value_col)
    ordered_index = _ordered_categories(pivot.index, GRADE_ORDER)
    pivot = pivot.reindex(ordered_index)
    if pivot.empty:
        raise ValueError("salary_by_grade_city_heatmap: got empty pivot table")

    numeric = pivot.astype(float)
    fig, ax = plt.subplots(figsize=HEATMAP_FIGSIZE)
    cax = ax.imshow(numeric.values, aspect="auto", cmap="coolwarm")
    ax.set_xticks(range(len(numeric.columns)))
    ax.set_xticklabels(numeric.columns)
    ax.set_yticks(range(len(numeric.index)))
    ax.set_yticklabels(numeric.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label=f"{value_col.capitalize()} зарплаты")
    ax.set_title("Зарплаты по грейду и типу города")
    return _finalize_figure(fig, "fig_salary_by_grade_city_heatmap.png", return_fig)


def work_mode_share_by_city(df: pd.DataFrame, return_fig: bool = False):
    _require_columns(df, ["city_tier", "work_mode"], "work_mode_share_by_city")
    df_local = df.copy()
    df_local["work_mode"] = pd.Categorical(
        df_local["work_mode"], categories=_ordered_categories(df_local["work_mode"].unique(), WORK_MODE_ORDER), ordered=True
    )
    pivot = pd.crosstab(df_local["city_tier"], df_local["work_mode"], normalize="index")
    pivot = pivot[_ordered_categories(pivot.columns, WORK_MODE_ORDER)]
    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    pivot.plot(kind="bar", stacked=True, ax=ax)
    ax.set_ylabel("Доля вакансий")
    ax.set_xlabel("Тип города")
    ax.set_title("Формат работы по типу города")
    ax.legend(title="Формат", bbox_to_anchor=(1.05, 1), loc="upper left")
    return _finalize_figure(fig, "fig_work_mode_share_by_city.png", return_fig)


def salary_by_role_work_mode_heatmap(
    summary_df: pd.DataFrame, value_col: str = "salary_median", return_fig: bool = False
):
    """Heatmap of salary metric by role (rows) and work mode (columns)."""

    _require_columns(summary_df, ["primary_role", "work_mode", value_col], "salary_by_role_work_mode_heatmap")
    pivot = summary_df.pivot(index="primary_role", columns="work_mode", values=value_col)
    pivot = pivot[_ordered_categories(pivot.columns, WORK_MODE_ORDER)]
    if pivot.empty:
        raise ValueError("salary_by_role_work_mode_heatmap: got empty pivot table")

    numeric = pivot.astype(float)
    fig, ax = plt.subplots(figsize=HEATMAP_FIGSIZE)
    cax = ax.imshow(numeric.values, aspect="auto", cmap="OrRd")
    ax.set_xticks(range(len(numeric.columns)))
    ax.set_xticklabels(numeric.columns)
    ax.set_yticks(range(len(numeric.index)))
    ax.set_yticklabels(numeric.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label=f"{value_col.capitalize()} зарплаты")
    ax.set_title("Зарплаты по ролям и формату работы")
    return _finalize_figure(fig, "fig_salary_by_role_work_mode_heatmap.png", return_fig)


def remote_share_by_role_bar(remote_df: pd.DataFrame, return_fig: bool = False):
    """Bar chart of remote vacancy share by primary role."""

    _require_columns(remote_df, ["primary_role", "remote_share"], "remote_share_by_role_bar")
    ordered = remote_df.sort_values(by="remote_share", ascending=False)
    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    ax.bar(ordered["primary_role"], ordered["remote_share"], color="teal")
    ax.set_ylabel("Доля удалёнки")
    ax.set_xlabel("Роль")
    ax.set_title("Удалённые вакансии по ролям")
    ax.tick_params(axis="x", rotation=45)
    return _finalize_figure(fig, "fig_remote_share_by_role.png", return_fig)


def top_skills_bar(
    df: pd.DataFrame,
    skill_cols: Sequence[str] | None = None,
    role_filter: str = "data",
    top_n: int = 15,
    return_fig: bool = False,
):
    _require_columns(df, ["primary_role"], "top_skills_bar")

    resolved_skill_cols = list(skill_cols) if skill_cols is not None else eda_mod.hard_skill_columns(df)
    missing_skills = [c for c in resolved_skill_cols if c not in df.columns]
    if missing_skills:
        raise ValueError(f"top_skills_bar: expected skill columns {missing_skills} to be present")

    role_mask = df["primary_role"].str.contains(role_filter, case=False, na=False)
    subset = df.loc[role_mask, resolved_skill_cols]
    if subset.empty:
        raise ValueError("top_skills_bar: no rows match the provided role_filter")

    numeric = subset.apply(pd.to_numeric, errors="coerce").fillna(0)
    counts = numeric.sum().sort_values(ascending=False).head(top_n)
    shares = counts / len(subset)
    stats = pd.DataFrame({"count": counts, "share": shares}).sort_values(by="share", ascending=False)

    humanized_labels = [_humanize_skill_name(skill) for skill in stats.index]
    positions = range(len(stats))

    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    bars = ax.bar(positions, stats["share"] * 100, color="steelblue")
    ax.set_ylabel("Доля вакансий с навыком, %")
    ax.set_xlabel("Навык")
    ax.set_title(f"Топ-{top_n} навыков для ролей с фильтром «{role_filter}»")
    ax.set_xticks(list(positions))
    ax.set_xticklabels(humanized_labels)
    ax.tick_params(axis="x", rotation=45, labelrotation=45)

    for bar, count, share in zip(bars, stats["count"], stats["share"]):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height,
            f"{share * 100:.1f}%\nN={count:.0f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    return _finalize_figure(fig, "fig_top_skills_data_bar.png", return_fig)


def skill_premium_bar(premium_df: pd.DataFrame, top_n: int = 10, return_fig: bool = False):
    _require_columns(premium_df, ["skill", "premium_pct"], "skill_premium_bar")
    top = premium_df.sort_values(by="premium_pct", ascending=False).head(top_n)
    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    ax.bar(top["skill"], top["premium_pct"])
    ax.set_ylabel("Премия к медиане, %")
    ax.set_xlabel("Навык")
    ax.set_title("Навыки с максимальной зарплатной премией")
    plt.xticks(rotation=60, ha="right")
    return _finalize_figure(fig, "fig_skill_premium_bar.png", return_fig)


def corr_heatmap(corr: pd.DataFrame, return_fig: bool = False):
    if corr.empty:
        raise ValueError("corr_heatmap: expected non-empty correlation matrix")
    fig, ax = plt.subplots(figsize=HEATMAP_FIGSIZE)
    cax = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=90)
    ax.set_yticks(range(len(corr.index)))
    ax.set_yticklabels(corr.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title("Корреляции числовых признаков")
    return _finalize_figure(fig, "fig_corr_heatmap.png", return_fig)


def skill_heatmap(
    df: pd.DataFrame,
    index_col: str,
    title: str,
    filename: str,
    skill_cols: Iterable[str] | None = None,
    top_n: int = 20,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Plot heatmap of skill prevalence across a categorical segment."""

    _require_columns(df, [index_col], "skill_heatmap")
    resolved_skills = eda_mod.hard_skill_columns(df) if skill_cols is None else list(skill_cols)
    present_skills = [col for col in resolved_skills if col in df.columns]
    if not present_skills:
        raise ValueError("skill_heatmap: expected at least one skill column")

    numeric_skills = df[present_skills].apply(pd.to_numeric, errors="coerce")
    freq = numeric_skills.mean().sort_values(ascending=False)
    top_skills = freq.head(top_n).index

    grouped = (
        pd.concat([df[[index_col]], numeric_skills[top_skills]], axis=1)
        .groupby(index_col)
        .mean()
    )
    pivot = grouped.fillna(0.0).astype(float)
    if pivot.empty:
        raise ValueError("Нет данных для построения heatmap")

    fig, ax = plt.subplots(figsize=HEATMAP_FIGSIZE)
    cax = ax.imshow(pivot.values.astype(float), aspect="auto", cmap="Blues")
    ax.set_xticks(range(len(top_skills)))
    ax.set_xticklabels(top_skills, rotation=90)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label="Доля вакансий")
    ax.set_title(title)
    return _finalize_figure(fig, filename, return_fig=return_fig)


def salary_mean_and_count_bar(
    df: pd.DataFrame,
    category_col: str,
    salary_col: str = "salary_mid_rub_capped",
    top_n: int = 10,
    figsize: tuple[int, int] = BAR_FIGSIZE,
    output_path: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Bar of median salary with vacancy counts on a twin axis for a category."""

    _require_columns(df, [category_col, salary_col], "salary_mean_and_count_bar")
    agg = df.groupby(category_col, observed=True)[salary_col].agg(median="median", mean="mean", count="count")
    top = agg.sort_values(by="count", ascending=False).head(top_n)
    if top.empty:
        raise ValueError("salary_mean_and_count_bar: no data after aggregation")

    if category_col == "grade":
        ordered_index = _ordered_categories(top.index, GRADE_ORDER)
        top = top.reindex(ordered_index).dropna(how="all")

    fig, ax1 = plt.subplots(figsize=figsize)
    ax1.bar(top.index, top["median"], color="steelblue")
    ax1.set_ylabel("Медианная зарплата (RUB)")
    ax1.set_xlabel(category_col)
    ax1.tick_params(axis="x", rotation=45)

    ax2 = ax1.twinx()
    ax2.plot(top.index, top["count"], color="darkorange", marker="o")
    ax2.set_ylabel("Количество вакансий")

    ax1.set_title(f"Зарплаты и объём вакансий по {category_col}")
    filename = output_path or FIGURES_DIR / f"fig_salary_{category_col}_mean_count.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def salary_by_city_mean_count_plot(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    top_n: int = 10,
    figsize: tuple[int, int] = BAR_FIGSIZE,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Wrapper for salary mean/count by city tier."""

    return salary_mean_and_count_bar(
        df,
        category_col="city_tier",
        salary_col=salary_col,
        top_n=top_n,
        figsize=figsize,
        output_path=FIGURES_DIR / "fig_salary_by_city_mean_count.png",
        return_fig=return_fig,
    )


def salary_by_grade_mean_count_plot(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    top_n: int = 10,
    figsize: tuple[int, int] = BAR_FIGSIZE,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Wrapper for salary mean/count by grade."""

    return salary_mean_and_count_bar(
        df,
        category_col="grade",
        salary_col=salary_col,
        top_n=top_n,
        figsize=figsize,
        output_path=FIGURES_DIR / "fig_salary_by_grade_mean_count.png",
        return_fig=return_fig,
    )


def salary_by_primary_role_mean_count_plot(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    top_n: int = 10,
    figsize: tuple[int, int] = BAR_FIGSIZE,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Wrapper for salary mean/count by primary role."""

    return salary_mean_and_count_bar(
        df,
        category_col="primary_role",
        salary_col=salary_col,
        top_n=top_n,
        figsize=figsize,
        output_path=FIGURES_DIR / "fig_salary_by_primary_role_mean_count.png",
        return_fig=return_fig,
    )


def salary_by_employer_rating_plot(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    top_n: int = 10,
    figsize: tuple[int, int] = BAR_FIGSIZE,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Wrapper for salary mean/count by employer rating buckets."""

    return salary_mean_and_count_bar(
        df,
        category_col="employer_rating",
        salary_col=salary_col,
        top_n=top_n,
        figsize=figsize,
        output_path=FIGURES_DIR / "fig_salary_by_employer_rating_mean_count.png",
        return_fig=return_fig,
    )


def salary_by_skills_bucket_plot(
    df: pd.DataFrame,
    salary_col: str = "salary_mid_rub_capped",
    top_n: int = 10,
    figsize: tuple[int, int] = BAR_FIGSIZE,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Wrapper for salary mean/count by tech stack size buckets."""

    category_col = "tech_stack_size"
    _require_columns(df, [category_col], "salary_by_skills_bucket_plot")
    # Bin stack size for readability
    bins = [-0.5, 2.5, 5.5, 10.5, float("inf")] if not df[category_col].isna().all() else [-0.5, 0.5, float("inf")]
    labels = ["0-2", "3-5", "6-10", "10+"] if len(bins) == 5 else ["0-1", "1+"]
    df_local = df.copy()
    df_local["stack_bucket"] = pd.cut(df_local[category_col].fillna(0), bins=bins, labels=labels, include_lowest=True)
    return salary_mean_and_count_bar(
        df_local,
        category_col="stack_bucket",
        salary_col=salary_col,
        top_n=top_n,
        figsize=figsize,
        output_path=FIGURES_DIR / "fig_salary_by_skills_bucket_mean_count.png",
        return_fig=return_fig,
    )


def salary_by_domain_plot(
    df: pd.DataFrame,
    top_n: int = 10,
    savepath: Path | None = None,
    priorities: list[str] | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Barplot of median salary by domain with vacancy counts on a twin axis.

    Args:
        df: Feature dataset containing ``domain_*`` columns and salaries.
        top_n: Number of domains to display.
        savepath: Optional custom output path.
        priorities: Optional ordered list of domain names (without ``domain_``
            prefix) to use when multiple domain flags are set for a vacancy.
    """

    from . import eda as eda_mod

    summary = eda_mod.describe_salary_by_domain(df, priorities=priorities)
    if summary.empty:
        raise ValueError("salary_by_domain_plot: expected domain_* columns and salary data")

    top = summary.sort_values(by="vacancy_count", ascending=False).head(top_n)
    fig, ax1 = plt.subplots(figsize=BAR_FIGSIZE)
    ax1.bar(top["domain"], top["salary_median"], color="steelblue")
    ax1.set_ylabel("Медианная зарплата (RUB)")
    ax1.set_xlabel("Домен")
    ax1.tick_params(axis="x", rotation=45, labelrotation=45)

    ax2 = ax1.twinx()
    ax2.plot(top["domain"], top["vacancy_count"], color="darkorange", marker="o")
    ax2.set_ylabel("Количество вакансий")

    ax1.set_title("Зарплаты и объём вакансий по доменам")
    filename = savepath or FIGURES_DIR / "fig_salary_by_domain.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def salary_by_english_level_plot(
    df: pd.DataFrame, savepath: Path | None = None, return_fig: bool = False
) -> Path | tuple[plt.Figure, Path]:
    """Barplot of median salary by English level."""

    from . import eda as eda_mod

    summary = eda_mod.english_requirement_stats(df)
    if summary.empty:
        raise ValueError("salary_by_english_level_plot: expected lang_* columns and salary data")

    summary["english_level"] = pd.Categorical(
        summary["english_level"], categories=_ordered_categories(summary["english_level"], ENGLISH_ORDER), ordered=True
    )
    ordered = summary.sort_values(by="english_level")
    label_map = {
        "no_english": "Английский не требуется",
        "a2": "A2 (Elementary)",
        "b1": "B1 (Intermediate)",
        "b2": "B2 (Upper-Intermediate)",
        "c1_plus": "C1+ (Advanced)",
        "unknown": "Требование не указано",
    }
    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    english_labels = [label_map.get(str(level), str(level)) for level in ordered["english_level"]]
    positions = range(len(ordered))
    ax.bar(positions, ordered["salary_median"], color="steelblue")
    ax.set_ylabel("Медианная зарплата (RUB)")
    ax.set_xlabel("Уровень английского")
    ax.set_xticks(positions, english_labels)
    ax.tick_params(axis="x", rotation=45, labelrotation=45)
    ax.set_title("Зарплаты по требуемому английскому")

    filename = savepath or FIGURES_DIR / "fig_salary_by_english_level.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def salary_by_education_level_plot(
    df: pd.DataFrame, savepath: Path | None = None, return_fig: bool = False
) -> Path | tuple[plt.Figure, Path]:
    """Barplot of median salary by education requirement level."""

    from . import eda as eda_mod

    summary = eda_mod.education_requirement_stats(df)
    if summary.empty:
        raise ValueError("salary_by_education_level_plot: expected edu_* columns and salary data")

    ordered = summary.sort_values(by="salary_median", ascending=False)
    fig, ax = plt.subplots(figsize=BAR_FIGSIZE)
    ax.bar(ordered["education_level"], ordered["salary_median"], color="seagreen")
    ax.set_ylabel("Медианная зарплата (RUB)")
    ax.set_xlabel("Уровень образования")
    ax.tick_params(axis="x", rotation=45, labelrotation=45)
    ax.set_title("Зарплаты по требованиям к образованию")

    filename = savepath or FIGURES_DIR / "fig_salary_by_education_level.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def heatmap_skills_by_grade(
    skill_share: pd.DataFrame,
    figsize: tuple[int, int] = HEATMAP_FIGSIZE,
    output_path: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Plot heatmap for skill (index) x grade (columns) share matrix."""

    if skill_share.empty:
        raise ValueError("heatmap_skills_by_grade: expected non-empty skill share matrix")
    if skill_share.columns.empty or skill_share.index.empty:
        raise ValueError("heatmap_skills_by_grade: matrix must have both index and columns")

    ordered_cols = _ordered_categories(skill_share.columns, GRADE_ORDER)
    numeric = skill_share[ordered_cols].astype(float)
    fig, ax = plt.subplots(figsize=figsize)
    cax = ax.imshow(numeric.values, aspect="auto", cmap="Blues")
    ax.set_xticks(range(len(numeric.columns)))
    ax.set_xticklabels(numeric.columns, rotation=90)
    humanized_skills = [_humanize_skill_name(skill) for skill in numeric.index]
    ax.set_yticks(range(len(numeric.index)))
    ax.set_yticklabels(humanized_skills)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label="Доля вакансий")
    ax.set_title("Навыки по грейдам")
    filename = output_path or FIGURES_DIR / "fig_skill_vs_grade_heatmap.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def heatmap_benefits_by_company(
    benefits_df: pd.DataFrame,
    figsize: tuple[int, int] = HEATMAP_FIGSIZE,
    output_path: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Plot heatmap for company x benefits matrix."""

    if benefits_df.empty:
        raise ValueError("heatmap_benefits_by_company: expected non-empty matrix")
    if benefits_df.columns.empty or benefits_df.index.empty:
        raise ValueError("heatmap_benefits_by_company: matrix must have both index and columns")

    numeric = benefits_df.astype(float)
    fig, ax = plt.subplots(figsize=figsize)
    cax = ax.imshow(numeric.values, aspect="auto", cmap="Greens")
    ax.set_xticks(range(len(numeric.columns)))
    ax.set_xticklabels(numeric.columns, rotation=90)
    ax.set_yticks(range(len(numeric.index)))
    ax.set_yticklabels(numeric.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label="Доля вакансий")
    ax.set_title("Пакеты бенефитов по компаниям")
    filename = output_path or FIGURES_DIR / "fig_benefits_by_company_heatmap.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def benefits_employer_heatmap(
    df: pd.DataFrame,
    top_n_employers: int = 10,
    top_n_benefits: int = 12,
    figsize: tuple[int, int] = HEATMAP_FIGSIZE,
    output_path: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Plot heatmap of benefit prevalence for top employers."""

    from . import eda as eda_mod

    summary = eda_mod.benefits_by_employer(df, top_n=top_n_employers)
    if summary.empty:
        raise ValueError("benefits_employer_heatmap: expected benefit_* columns and company data")

    benefit_cols = [col for col in summary.columns if col.startswith("benefit_")]
    if not benefit_cols:
        raise ValueError("benefits_employer_heatmap: no benefit columns found after aggregation")

    benefit_order = summary[benefit_cols].mean().sort_values(ascending=False)
    top_benefits = benefit_order.head(top_n_benefits).index if top_n_benefits else benefit_cols

    pivot = summary.set_index("company")[list(top_benefits)]
    fig, ax = plt.subplots(figsize=figsize)
    cax = ax.imshow(pivot.values.astype(float), aspect="auto", cmap="Greens")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=90)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label="Доля вакансий")
    ax.set_title("Бенефиты у топовых работодателей")
    filename = output_path or FIGURES_DIR / "fig_benefits_employer_heatmap.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def heatmap_soft_skills_correlation(
    corr_df: pd.DataFrame,
    figsize: tuple[int, int] = HEATMAP_FIGSIZE,
    output_path: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Plot correlation heatmap for soft skill columns."""

    if corr_df.empty:
        raise ValueError("heatmap_soft_skills_correlation: expected non-empty correlation matrix")
    if corr_df.shape[0] != corr_df.shape[1]:
        raise ValueError("heatmap_soft_skills_correlation: matrix must be square")

    fig, ax = plt.subplots(figsize=figsize)
    cax = ax.imshow(corr_df.values.astype(float), cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr_df.columns)))
    ax.set_xticklabels(corr_df.columns, rotation=90)
    ax.set_yticks(range(len(corr_df.index)))
    ax.set_yticklabels(corr_df.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label="Корреляция")
    ax.set_title("Корреляции между soft skills")
    filename = output_path or FIGURES_DIR / "fig_soft_skills_corr_heatmap.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def soft_skills_employer_heatmap(
    df: pd.DataFrame,
    top_n_employers: int = 10,
    top_n_skills: int = 12,
    figsize: tuple[int, int] = HEATMAP_FIGSIZE,
    output_path: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Plot heatmap of soft skill prevalence for top employers."""

    from . import eda as eda_mod

    summary = eda_mod.soft_skills_by_employer(df, top_n=top_n_employers)
    if summary.empty:
        raise ValueError("soft_skills_employer_heatmap: expected soft_* columns and company data")

    skill_cols = [col for col in summary.columns if col.startswith("soft_")]
    if not skill_cols:
        raise ValueError("soft_skills_employer_heatmap: no soft skill columns found after aggregation")

    skill_order = summary[skill_cols].mean().sort_values(ascending=False)
    top_skills = skill_order.head(top_n_skills).index if top_n_skills else skill_cols

    pivot = summary.set_index("company")[list(top_skills)]
    fig, ax = plt.subplots(figsize=figsize)
    cax = ax.imshow(pivot.values.astype(float), aspect="auto", cmap="Blues")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=90)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label="Доля вакансий")
    ax.set_title("Soft skills у топовых работодателей")
    filename = output_path or FIGURES_DIR / "fig_soft_skills_employer_heatmap.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)


def distribution_with_boxplot(
    df: pd.DataFrame,
    column: str,
    bins: int = 30,
    figsize: tuple[int, int] = BAR_FIGSIZE,
    output_path: Path | None = None,
    return_fig: bool = False,
) -> Path | tuple[plt.Figure, Path]:
    """Histogram plus boxplot for a numeric column."""

    _require_columns(df, [column], "distribution_with_boxplot")
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        raise ValueError("distribution_with_boxplot: no numeric data to plot")

    fig, (ax_hist, ax_box) = plt.subplots(
        2, 1, figsize=figsize, gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )
    ax_hist.hist(series, bins=bins, color="steelblue", edgecolor="white")
    ax_hist.set_ylabel("Количество")
    ax_hist.set_title(f"Распределение {column}")

    ax_box.boxplot(series, vert=False)
    ax_box.set_xlabel(column)

    filename = output_path or FIGURES_DIR / f"fig_dist_{column}.png"
    return _finalize_figure(fig, filename, return_fig=return_fig)
