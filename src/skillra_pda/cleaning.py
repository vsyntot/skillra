"""Data cleaning helpers for the Skillra PDA project."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

PREFIX_GROUPS = ["is_", "has_", "skill_", "benefit_", "soft_", "domain_", "role_"]

LOW_INFORMATION_THRESHOLD = 0.90
LOW_INFORMATION_WHITELIST = {
    "salary_from",
    "salary_to",
    "salary_mid",
    "salary_mid_rub",
    "salary_mid_rub_capped",
    "salary_known",
    "salary_gross",
    "currency",
    "grade",
    "grade_final",
    "primary_role",
    "work_format",
    "work_mode",
    "employment_type",
    "schedule",
    "city",
    "city_tier",
    "country",
    "region",
    "city_normalized",
    "geo_scope",
    "experience",
    "lang_english_level",
    "lang_english_required",
    "edu_level",
    "edu_required",
    "published_at_iso",
    "scraped_at_utc",
    "vacancy_age_days",
}

# Declarative missingness handling rules
# Only explicit categorical columns are filled with "unknown" to preserve
# semantic categories where "не указано" is meaningful. Everything else keeps
# NaN for honest coverage in EDA.
CATEGORICAL_IMPUTE_MAP: Dict[str, str] = {
    "grade": "unknown",
    "work_format": "unknown",
    "work_mode": "unknown",
    "employment_type": "unknown",
    "schedule": "unknown",
    "city_tier": "unknown",
    "country": "unknown",
    "region": "unknown",
    "city_normalized": "unknown",
    "geo_scope": "unknown",
    "lang_english_level": "unknown",
    "employer_type": "unknown",
}

# Numeric imputations are only allowed for explicit counters. Salary/rating
# values are intentionally left as NaN to reflect missingness in the source.
NUMERIC_IMPUTE_RULES: Dict[str, float | int] = {
    # Employer/platform counters
    "employer_reviews_count": 0,
    # Text structure counters
    "description_bullets_count": 0,
    "description_paragraphs_count": 0,
    "requirements_count": 0,
    "responsibilities_count": 0,
    "must_have_skills_count": 0,
    "optional_skills_count": 0,
    # Boolean aggregation counters
    "role_count": 0,
    "skills_count": 0,
    "benefits_count": 0,
    "soft_skills_count": 0,
    "hard_stack_count": 0,
    "core_data_skills_count": 0,
    "ml_stack_count": 0,
    "tech_stack_size": 0,
    # Location/transport counters
    "metro_count": 0,
    # Language/other counters
    "lang_other_count": 0,
}

KEY_COLUMN_COMMENTS: Dict[str, str] = {
    "salary_from": "зарплата отсутствует в исходной вакансии",
    "salary_to": "зарплата отсутствует в исходной вакансии",
    "employer_rating": "отзывов/рейтинга на hh нет",
    "salary_mid": "расчёт от исходной вилки; NaN если вилка не указана",
    "work_mode": '"unknown" = формат работы не распознан',
    "work_format": '"unknown" = формат работы не распознан',
    "grade": '"unknown" = грейд не удалось определить',
    "lang_english_level": '"unknown" = нет явного требования по английскому',
}

# Unified markers that represent unknown or missing text values
UNKNOWN_MARKERS = {
    "unknown",
    "Unknown",
    "UNKNOWN",
    "не указано",
    "Не указано",
    "неизвестно",
    "",
    " ",
    "n/a",
    "N/A",
    "nan",
    "-",
    "—",
}

BOOL_NULL_MARKERS = {m.strip().lower() for m in UNKNOWN_MARKERS if isinstance(m, str)}
BOOL_TRUE_MARKERS = {True, 1, "1", "true", "yes"}
BOOL_FALSE_MARKERS = {False, 0, "0", "false", "no"}
BOOLEAN_MARKERS = BOOL_TRUE_MARKERS | BOOL_FALSE_MARKERS | BOOL_NULL_MARKERS


def _normalize_bool_like(value, null_lower: set) -> object:
    """Normalize a single value to True/False/pd.NA if it is boolean-like.

    Returns None when the value is not recognized as boolean-like.
    """

    if pd.isna(value):
        return pd.NA

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, np.integer)):
        if value in (0, 1):
            return bool(value)
        return None

    if isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()
        if lowered in null_lower:
            return pd.NA
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False

    return None


def coerce_bool_like_series(
    series: pd.Series,
    null_markers: Iterable[str] | None = None,
    force: bool = False,
) -> Tuple[pd.Series, bool]:
    """Convert boolean-like values to pandas nullable boolean dtype.

    Parameters
    ----------
    series : pd.Series
        Series to process.
    null_markers : Iterable[str] | None, optional
        Markers that should be treated as null/unknown before casting.
    force : bool, optional
        If True, unrecognized values are coerced to NA to allow casting. If
        False, the function returns (series, False) when encountering
        non-boolean-like values.
    """

    markers = set(null_markers) if null_markers is not None else BOOL_NULL_MARKERS
    null_lower = {m.strip().lower() for m in markers}

    uniques = series.dropna().unique()
    for val in uniques:
        normalized = _normalize_bool_like(val, null_lower)
        if normalized is None and not force:
            return series, False

    def _convert(val):
        normalized = _normalize_bool_like(val, null_lower)
        if normalized is None:
            return pd.NA if force else normalized
        return normalized

    coerced = series.map(_convert)
    if not force and coerced.isna().any() and len(series.dropna()) > 0:
        return series, False

    return coerced.astype("boolean"), True


def is_boolean_like_series(series: pd.Series, null_markers: Iterable[str] | None = None) -> bool:
    """Check whether a series only contains boolean-like values (plus null markers).

    Nulls are ignored for the check; any non-boolean-like value will return False.
    """

    markers = set(null_markers) if null_markers is not None else BOOL_NULL_MARKERS
    null_lower = {m.strip().lower() for m in markers}

    uniques = series.dropna().unique()
    for val in uniques:
        normalized = _normalize_bool_like(val, null_lower)
        if normalized is None:
            return False
    return True


def _drop_mostly_missing_columns(df: pd.DataFrame, threshold: float = 0.95) -> Tuple[pd.DataFrame, List[str]]:
    """Drop columns whose missingness exceeds the threshold."""

    missing_share = df.isna().mean()
    to_drop = missing_share[missing_share >= threshold].index.tolist()
    if to_drop:
        df = df.drop(columns=to_drop)
    return df, to_drop


def _coerce_boolean_like_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """Coerce boolean-like columns (including salary_gross and prefixed bools)."""

    bool_like_cols: List[str] = []
    allowed_values = BOOLEAN_MARKERS | {True, False, 0, 1}
    replace_map = {
        "true": True,
        "1": True,
        "yes": True,
        "false": False,
        "0": False,
        "no": False,
        "unknown": pd.NA,
        "": pd.NA,
        "n/a": pd.NA,
        "nan": pd.NA,
    }

    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)
        prefix_candidate = any(col.startswith(prefix) for prefix in PREFIX_GROUPS)
        force = prefix_candidate or col == "salary_gross" or dtype_str in {"bool", "boolean"}

        uniques = series.dropna().unique()
        normalized_uniques = set()
        for val in uniques:
            if isinstance(val, str):
                normalized_uniques.add(val.strip().lower())
            else:
                normalized_uniques.add(val)

        subset_bool_like = all(u in allowed_values for u in normalized_uniques) or not normalized_uniques
        if not (subset_bool_like or force):
            continue

        def _convert(val: object) -> object:
            if pd.isna(val):
                return pd.NA
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, np.integer)) and val in (0, 1):
                return bool(val)
            if isinstance(val, str):
                lowered = val.strip().lower()
                if lowered in replace_map:
                    return replace_map[lowered]
            return pd.NA if force else None

        coerced = series.map(_convert)
        if coerced.isna().any() and not force and not subset_bool_like:
            continue

        df[col] = coerced.astype("boolean")
        bool_like_cols.append(col)

    return df, bool_like_cols


def _fill_categorical_missing(
    df: pd.DataFrame, fill_map: Dict[str, str] | None = None
) -> Tuple[pd.DataFrame, List[str]]:
    """Fill missing values in selected categorical/object columns."""

    if fill_map is None:
        fill_map = {}

    filled_cols: List[str] = []

    for col, fill_value in fill_map.items():
        if col not in df.columns:
            continue
        dtype_str = str(df[col].dtype)
        if dtype_str != "object" and not dtype_str.startswith("category"):
            continue
        if df[col].isna().any():
            df[col] = df[col].fillna(fill_value)
            filled_cols.append(col)

    return df, filled_cols


def standardize_unknown_markers(
    df: pd.DataFrame, markers: Iterable[str] | None = None
) -> Tuple[pd.DataFrame, List[str]]:
    """Replace textual unknown markers with ``pd.NA`` for string-like columns.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe to process. A copy is returned.
    markers : Iterable[str] | None
        Collection of textual markers representing unknown values. Defaults to
        ``UNKNOWN_MARKERS``.

    Returns
    -------
    Tuple[pd.DataFrame, List[str]]
        Updated dataframe and the list of columns where replacements occurred.
    """

    df = df.copy()
    markers_set = {m.strip().lower() for m in (markers or UNKNOWN_MARKERS)}
    affected: List[str] = []

    def is_marker(val: object) -> bool:
        return isinstance(val, str) and val.strip().lower() in markers_set

    for col in df.columns:
        dtype_str = str(df[col].dtype)
        if dtype_str != "object" and not dtype_str.startswith("category"):
            continue
        series = df[col]
        mask = series.map(is_marker)
        if mask.any():
            df[col] = series.mask(mask, pd.NA)
            affected.append(col)

    return df, affected


def _fill_numeric_missing(
    df: pd.DataFrame, fill_map: Dict[str, float | int] | None = None
) -> Tuple[pd.DataFrame, List[str]]:
    """Fill missing numeric columns according to explicit rules."""

    if fill_map is None:
        fill_map = {}

    filled_cols: List[str] = []
    numeric_cols = df.select_dtypes(include=["number"]).columns
    for col in numeric_cols:
        fill_value: float | int | None = None

        if col in fill_map:
            fill_value = fill_map[col]
        elif col.endswith("_count"):
            fill_value = 0

        if fill_value is None or not df[col].isna().any():
            continue

        df[col] = df[col].fillna(fill_value)
        filled_cols.append(col)
    return df, filled_cols


def normalize_boolean_columns(
    df: pd.DataFrame,
    null_markers: Iterable[str] | None = None,
    force_columns: Iterable[str] | None = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """Coerce boolean-like columns to pandas nullable booleans.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe. It is modified in place.
    null_markers : Iterable[str] | None
        Markers that should be treated as unknown/NA before coercion.
    force_columns : Iterable[str] | None
        Columns that must be coerced regardless of boolean-likeness checks.
    """

    markers = set(null_markers) if null_markers is not None else BOOL_NULL_MARKERS
    forced = set(force_columns) if force_columns is not None else set()
    boolean_cols: List[str] = []

    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)

        if dtype_str == "boolean":
            boolean_cols.append(col)
            continue

        should_force = col in forced
        should_try = should_force or dtype_str == "bool" or dtype_str.startswith("bool")
        should_try = should_try or is_boolean_like_series(series, null_markers=markers)

        if not should_try:
            continue

        coerced, did_cast = coerce_bool_like_series(series, null_markers=markers, force=True)
        if should_force or did_cast:
            df[col] = coerced
            boolean_cols.append(col)

    return df, boolean_cols


def basic_profile(df: pd.DataFrame) -> Dict[str, object]:
    """Return a lightweight profile of the dataframe."""
    missing = df.isna().mean().sort_values(ascending=False).head(20)
    dtypes_summary = df.dtypes.astype(str).value_counts().to_dict()
    profile = {
        "shape": df.shape,
        "dtypes_summary": dtypes_summary,
        "missing_top20": missing,
    }
    return profile


def check_unique_id(df: pd.DataFrame, id_col: str = "vacancy_id") -> Tuple[bool, int]:
    """Check whether an identifier column is unique.

    Returns a tuple of (is_unique, duplicate_count).
    """
    duplicates = df.duplicated(subset=[id_col]).sum()
    return duplicates == 0, int(duplicates)


def detect_column_groups(df: pd.DataFrame) -> Dict[str, List[str]]:
    """Group columns by business prefixes."""
    groups: Dict[str, List[str]] = {prefix: [] for prefix in PREFIX_GROUPS}
    for col in df.columns:
        for prefix in PREFIX_GROUPS:
            if col.startswith(prefix):
                groups[prefix].append(col)
    return groups


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse timestamp-like columns into datetimes."""
    date_cols = ["published_at_iso", "scraped_at_utc"]
    for col in date_cols:
        if col in df.columns:
            # align on UTC to avoid tz-naive/aware subtraction issues
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    if "published_at_iso" in df.columns and "scraped_at_utc" in df.columns:
        df["vacancy_age_days"] = (df["scraped_at_utc"] - df["published_at_iso"]).dt.days
        # store tz-naive versions for downstream use
        df["published_at_iso"] = df["published_at_iso"].dt.tz_convert(None)
        df["scraped_at_utc"] = df["scraped_at_utc"].dt.tz_convert(None)
    return df


def handle_missingness(df: pd.DataFrame, drop_threshold: float = LOW_INFORMATION_THRESHOLD) -> pd.DataFrame:
    """Handle missing values using declarative sub-steps.

    The function standardizes textual unknown markers, drops
    low-information columns based on the effective missingness share, coerces
    boolean-like fields, and applies targeted imputations for categorical and
    numeric counters.
    """

    df = df.copy()

    df, normalized_unknown_cols = standardize_unknown_markers(df)
    df, dropped_low_info, retained_low_info, low_info_table = drop_low_information_columns(df, threshold=drop_threshold)
    df, bool_like_cols = _coerce_boolean_like_columns(df)
    df, filled_categorical_cols = _fill_categorical_missing(df, fill_map=CATEGORICAL_IMPUTE_MAP)
    df, filled_numeric_cols = _fill_numeric_missing(df, fill_map=NUMERIC_IMPUTE_RULES)

    low_info_report = low_info_table.to_dict(orient="records")

    df.attrs["normalized_unknown_cols"] = normalized_unknown_cols
    df.attrs["dropped_cols"] = dropped_low_info
    df.attrs["low_info_report"] = low_info_report
    df.attrs["low_info_retained"] = retained_low_info
    df.attrs["low_info_threshold"] = drop_threshold
    df.attrs["bool_like_cols"] = bool_like_cols
    df.attrs["filled_categorical_cols"] = filled_categorical_cols
    df.attrs["filled_numeric_cols"] = filled_numeric_cols

    return df


def ensure_salary_gross_boolean(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee salary_gross is a nullable boolean without stray string markers."""

    if "salary_gross" not in df.columns:
        return df

    replacement_map = {
        **{m: pd.NA for m in UNKNOWN_MARKERS if isinstance(m, str)},
        "true": True,
        "false": False,
        "yes": True,
        "no": False,
        "True": True,
        "False": False,
        "1": True,
        "0": False,
    }

    series = df["salary_gross"].copy()
    if series.dtype == "object":
        series = series.replace(replacement_map)

    coerced, _ = coerce_bool_like_series(series, null_markers=BOOL_NULL_MARKERS, force=True)
    df["salary_gross"] = coerced.astype("boolean")
    return df


def summarize_data_health(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    """Summarize data health: dtype, missingness metrics, and comments.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe to summarize.
    prefix : str, optional
        Optional prefix for column names in the report.

    Returns
    -------
    pd.DataFrame
        Table with columns: column, dtype, share_nan, share_unknown_marker,
        effective_missing_share, coverage_share, quality_bucket,
        recommended_use, comment.
    """

    markers_set = {m.strip().lower() for m in UNKNOWN_MARKERS}
    records: List[Dict[str, object]] = []

    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)
        nan_share = float(series.isna().mean())

        marker_share = 0.0
        if dtype_str == "object" or dtype_str.startswith("category"):
            marker_mask = series.apply(lambda v: isinstance(v, str) and v.strip().lower() in markers_set)
            marker_share = float(marker_mask.mean())

        effective_missing_share = nan_share + (marker_share if marker_share else 0.0)
        effective_missing_share = min(effective_missing_share, 1.0)
        coverage_share = max(0.0, 1.0 - effective_missing_share)

        if coverage_share >= 0.85:
            quality_bucket = "high"
            recommended_use = "ok_for_conclusions"
        elif coverage_share >= 0.60:
            quality_bucket = "medium"
            recommended_use = "ok_with_disclaimer"
        elif coverage_share >= 0.30:
            quality_bucket = "low"
            recommended_use = "only_hypothesis"
        else:
            quality_bucket = "critical"
            recommended_use = "ignore"

        comment_parts: List[str] = []
        base_comment = KEY_COLUMN_COMMENTS.get(col)
        if base_comment:
            comment_parts.append(base_comment)
        if nan_share > 0:
            comment_parts.append(f"NaN {nan_share:.1%}")
        if marker_share > 0:
            comment_parts.append(f"text marker {marker_share:.1%}")

        comment = "; ".join(comment_parts) if comment_parts else "clean"
        records.append(
            {
                "column": f"{prefix}{col}" if prefix else col,
                "dtype": dtype_str,
                "share_nan": nan_share,
                "share_unknown_marker": marker_share,
                "effective_missing_share": effective_missing_share,
                "coverage_share": coverage_share,
                "quality_bucket": quality_bucket,
                "recommended_use": recommended_use,
                "comment": comment,
            }
        )

    return pd.DataFrame(records)


def list_low_information_columns(df: pd.DataFrame, threshold: float = 0.90) -> pd.DataFrame:
    """List columns whose effective missingness exceeds a threshold.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe to analyze.
    threshold : float, optional
        Minimum effective missingness share for a column to be included. The
        value is expected in the ``[0, 1]`` range. Defaults to ``0.90``.

    Returns
    -------
    pd.DataFrame
        Table with columns ``column``, ``dtype``, ``na_share``,
        ``unknown_share`` and ``effective_missing_share`` sorted by descending
        effective missingness.
    """

    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")

    health = summarize_data_health(df)
    low_info = health[health["effective_missing_share"] >= threshold].copy()

    low_info = low_info.rename(
        columns={
            "share_nan": "na_share",
            "share_unknown_marker": "unknown_share",
        }
    )
    columns = ["column", "dtype", "na_share", "unknown_share", "effective_missing_share"]
    return low_info[columns].sort_values(by="effective_missing_share", ascending=False).reset_index(drop=True)


def drop_low_information_columns(
    df: pd.DataFrame,
    threshold: float = LOW_INFORMATION_THRESHOLD,
    whitelist: Iterable[str] | None = None,
) -> Tuple[pd.DataFrame, List[str], List[str], pd.DataFrame]:
    """Drop columns whose effective missingness exceeds a threshold.

    Parameters
    ----------
    df : pd.DataFrame
        Input dataframe to process.
    threshold : float, optional
        Maximum tolerated effective missingness. Columns with
        ``effective_missing_share`` greater than or equal to the threshold will
        be removed unless present in the whitelist. Defaults to
        ``LOW_INFORMATION_THRESHOLD``.
    whitelist : Iterable[str] | None, optional
        Columns that should be preserved even if they exceed the threshold.

    Returns
    -------
    Tuple[pd.DataFrame, List[str], List[str], pd.DataFrame]
        Updated dataframe, list of dropped columns, list of retained
        low-information columns (because of the whitelist), and the full
        low-information table.
    """

    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")

    whitelist_set = set(LOW_INFORMATION_WHITELIST if whitelist is None else whitelist)
    low_info_table = list_low_information_columns(df, threshold=threshold)

    to_drop = [col for col in low_info_table["column"] if col not in whitelist_set]
    retained = [col for col in low_info_table["column"] if col in whitelist_set]

    if to_drop:
        df = df.drop(columns=to_drop)

    return df, to_drop, retained, low_info_table


def salary_prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Create salary helper columns and cap outliers for RUB."""
    if "salary_mid" in df.columns:
        currency_series = df.get("currency")
        mask = currency_series == "RUB" if currency_series is not None else False
        if isinstance(mask, pd.Series):
            mask = mask.fillna(False)
        df["salary_mid_rub"] = np.where(mask, df["salary_mid"], np.nan)
    else:
        df["salary_mid_rub"] = np.nan

    df["salary_known"] = df["salary_mid_rub"].notna()

    if df["salary_mid_rub"].notna().any():
        lower = df["salary_mid_rub"].quantile(0.01)
        upper = df["salary_mid_rub"].quantile(0.99)
        df["salary_mid_rub_capped"] = df["salary_mid_rub"].clip(lower=lower, upper=upper)
    else:
        df["salary_mid_rub_capped"] = df["salary_mid_rub"]

    non_rub_share = df.get("currency").fillna("").ne("RUB").mean() if "currency" in df.columns else 0.0
    df.attrs["non_rub_share"] = non_rub_share
    return df


def deduplicate(df: pd.DataFrame, id_col: str = "vacancy_id") -> pd.DataFrame:
    """Remove duplicate vacancies keeping the latest scrape."""
    if id_col not in df.columns:
        return df

    sort_col = "scraped_at_utc" if "scraped_at_utc" in df.columns else None
    if sort_col:
        df = df.sort_values(by=sort_col, ascending=False)
    before = len(df)
    df = df.drop_duplicates(subset=[id_col], keep="first")
    df.attrs["deduplicated_rows"] = before - len(df)
    return df
