"""Feature engineering utilities aligned with the project plan."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd

from .cleaning import detect_column_groups

CITY_MILLION_PLUS = {
    "novosibirsk",
    "yekaterinburg",
    "ekaterinburg",
    "nizhny novgorod",
    "нижний новгород",
    "nn",
    "kazan",
    "казань",
    "chelyabinsk",
    "челябинск",
    "samara",
    "самара",
    "omsk",
    "омск",
    "rostov-on-don",
    "rostov-na-donu",
    "ростов-на-дону",
    "ufa",
    "уфа",
    "krasnoyarsk",
    "красноярск",
    "perm",
    "пермь",
    "voronezh",
    "воронеж",
    "volgograd",
    "волгоград",
    "krasnodar",
    "краснодар",
}

AREA_GEO_DEFAULTS: dict[int, tuple[str, str, str]] = {
    1: ("Russia", "Moscow", "Moscow"),
    2: ("Russia", "Saint Petersburg", "Saint Petersburg"),
    5: ("Ukraine", "unknown", "unknown"),
    40: ("Belarus", "unknown", "unknown"),
    51: ("Georgia", "unknown", "unknown"),
    111: ("Moldova", "unknown", "unknown"),
    113: ("Russia", "unknown", "unknown"),
    159: ("Kazakhstan", "unknown", "unknown"),
    160: ("Armenia", "unknown", "unknown"),
    194: ("Tajikistan", "unknown", "unknown"),
    204: ("Azerbaijan", "unknown", "unknown"),
    218: ("Turkmenistan", "unknown", "unknown"),
    237: ("Uzbekistan", "unknown", "unknown"),
    246: ("Kyrgyzstan", "unknown", "unknown"),
}

CITY_GEO_ALIASES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("Russia", "Moscow", "Moscow", ("moscow", "москва", "моск")),
    (
        "Russia",
        "Saint Petersburg",
        "Saint Petersburg",
        ("saint petersburg", "st petersburg", "spb", "санкт-петербург", "петербург", "спб"),
    ),
    ("Russia", "Tatarstan", "Kazan", ("kazan", "казань")),
    ("Russia", "Novosibirsk Oblast", "Novosibirsk", ("novosibirsk", "новосибирск")),
    ("Russia", "Sverdlovsk Oblast", "Yekaterinburg", ("yekaterinburg", "ekaterinburg", "екатеринбург")),
    ("Russia", "Nizhny Novgorod Oblast", "Nizhny Novgorod", ("nizhny novgorod", "нижний новгород")),
    ("Russia", "Chelyabinsk Oblast", "Chelyabinsk", ("chelyabinsk", "челябинск")),
    ("Russia", "Samara Oblast", "Samara", ("samara", "самара")),
    ("Russia", "Omsk Oblast", "Omsk", ("omsk", "омск")),
    ("Russia", "Rostov Oblast", "Rostov-on-Don", ("rostov-on-don", "rostov-na-donu", "ростов-на-дону")),
    ("Russia", "Bashkortostan", "Ufa", ("ufa", "уфа")),
    ("Russia", "Krasnoyarsk Krai", "Krasnoyarsk", ("krasnoyarsk", "красноярск")),
    ("Russia", "Perm Krai", "Perm", ("perm", "пермь")),
    ("Russia", "Voronezh Oblast", "Voronezh", ("voronezh", "воронеж")),
    ("Russia", "Volgograd Oblast", "Volgograd", ("volgograd", "волгоград")),
    ("Russia", "Krasnodar Krai", "Krasnodar", ("krasnodar", "краснодар")),
    ("Kazakhstan", "Almaty", "Almaty", ("almaty", "алматы")),
    ("Kazakhstan", "Astana", "Astana", ("astana", "nursultan", "nur-sultan", "нур-султан", "астана")),
    ("Belarus", "Minsk", "Minsk", ("minsk", "минск")),
    ("Armenia", "Yerevan", "Yerevan", ("yerevan", "ереван")),
    ("Georgia", "Tbilisi", "Tbilisi", ("tbilisi", "тбилиси")),
    ("Uzbekistan", "Tashkent", "Tashkent", ("tashkent", "ташкент")),
]

COUNTRY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Kazakhstan", ("kazakhstan", "kazakh", "казахстан", "кз", "kz")),
    ("Belarus", ("belarus", "беларус", "белорус", "минск")),
    ("Armenia", ("armenia", "армения", "ереван")),
    ("Georgia", ("georgia", "грузия", "тбилиси")),
    ("Uzbekistan", ("uzbekistan", "узбекистан", "ташкент")),
    ("Kyrgyzstan", ("kyrgyzstan", "киргиз", "кыргыз")),
    ("Azerbaijan", ("azerbaijan", "азербайджан", "баку")),
    ("Russia", ("russia", "россия", "москва", "петербург")),
]

PRIMARY_ROLE_PRIORITY = [
    "role_ml",
    "role_data",
    "role_devops",
    "role_backend",
    "role_frontend",
    "role_fullstack",
    "role_mobile",
    "role_qa",
    "role_product",
    "role_manager",
    "role_analyst",
]

PRIMARY_ROLE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("ml", ["machine learning", "ml engineer", "ml-", "ml ", "deep learning"]),
    (
        "data",
        [
            "data engineer",
            "data scientist",
            "data science",
            "dwh",
            "etl",
        ],
    ),
    (
        "devops",
        ["devops", "sre", "site reliability", "platform engineer", "infrastructure"],
    ),
    (
        "backend",
        [
            "backend",
            "back-end",
            "back end",
            "server",
            "python developer",
            "java developer",
            "go developer",
            ".net",
            "node.js",
            "nodejs",
        ],
    ),
    ("frontend", ["frontend", "front-end", "front end", "javascript", "react", "vue", "angular"]),
    ("fullstack", ["fullstack", "full-stack", "full stack"]),
    ("mobile", ["android", "ios", "mobile", "swift", "kotlin"]),
    (
        "qa",
        ["qa", "quality assurance", "test engineer", "testing", "тестиров"],
    ),
    ("product", ["product manager", "product owner", "продакт", "product lead"]),
    (
        "manager",
        ["project manager", "delivery manager", "program manager", "руководитель", "team lead", "tech lead"],
    ),
    (
        "analyst",
        [
            "analyst",
            "аналитик",
            "business intelligence",
            "bi analyst",
            "system analyst",
            "product analyst",
        ],
    ),
]

# Skill group definitions guided by the feature dictionary
CORE_DATA_SKILLS = [
    "skill_sql",
    "skill_excel",
    "skill_powerbi",
    "skill_tableau",
    "skill_r",
    "has_python",
    "skill_clickhouse",
    "skill_bigquery",
]

ML_STACK_SKILLS = [
    "has_sklearn",
    "has_pytorch",
    "has_tensorflow",
    "has_airflow",
    "has_spark",
    "has_kafka",
]


def _experience_to_grade(years: float | None, no_experience_flag: bool | None, raw: str | None) -> str:
    """Infer grade bucket from experience markers."""

    if isinstance(no_experience_flag, (bool, np.bool_)) and no_experience_flag:
        return "intern"

    if years is not None and not pd.isna(years):
        if years < 1:
            return "intern"
        if years < 3:
            return "junior"
        if years < 5:
            return "middle"
        if years < 8:
            return "senior"
        return "lead"

    if isinstance(raw, str):
        raw_lower = raw.lower()
        if "не треб" in raw_lower or "no experience" in raw_lower or "без опыта" in raw_lower:
            return "intern"
        if "1-3" in raw_lower or "1–3" in raw_lower or "1 to 3" in raw_lower:
            return "junior"
        if "3-6" in raw_lower or "3–6" in raw_lower or "3 to 6" in raw_lower:
            return "middle"
        if "6" in raw_lower:
            return "senior"

    return "unknown"


def add_grade_from_experience(df: pd.DataFrame) -> pd.DataFrame:
    """Derive grade_from_experience using exp_min/max and raw markers."""

    df = df.copy()
    min_years = pd.to_numeric(df.get("exp_min_years"), errors="coerce") if "exp_min_years" in df else None
    max_years = pd.to_numeric(df.get("exp_max_years"), errors="coerce") if "exp_max_years" in df else None
    base_years = None
    if min_years is not None:
        base_years = min_years
        if max_years is not None:
            base_years = base_years.fillna(max_years)
    elif max_years is not None:
        base_years = max_years
    else:
        base_years = pd.Series(pd.NA, index=df.index)

    exp_flag = df.get("exp_is_no_experience") if "exp_is_no_experience" in df else None
    raw_exp = df.get("experience") if "experience" in df else None

    df["grade_from_experience"] = [
        _experience_to_grade(
            float(years) if years is not None and not pd.isna(years) else None,
            exp_flag.iloc[i] if exp_flag is not None else None,
            raw_exp.iloc[i] if raw_exp is not None else None,
        )
        for i, years in enumerate(base_years)
    ]
    return df


def add_time_features(df: pd.DataFrame, date_col: str = "published_at_iso") -> pd.DataFrame:
    """Add weekday/month/is_weekend flags from the publication date and vacancy age."""
    if date_col in df.columns:
        dt = pd.to_datetime(df[date_col], errors="coerce")
        df["published_weekday"] = dt.dt.weekday
        df["published_month"] = dt.dt.month
        df["is_weekend_post"] = dt.dt.weekday.isin([5, 6])
    else:
        # Keep downstream expectations stable even if the source column was dropped upstream.
        df["published_weekday"] = pd.NA
        df["published_month"] = pd.NA
        df["is_weekend_post"] = pd.NA

    if "scraped_at_utc" in df.columns and date_col in df.columns:
        scraped = pd.to_datetime(df["scraped_at_utc"], errors="coerce", utc=True).dt.tz_convert(None)
        published = pd.to_datetime(df[date_col], errors="coerce", utc=True).dt.tz_convert(None)
        df["vacancy_age_days"] = (scraped - published).dt.days
    else:
        df["vacancy_age_days"] = pd.NA
    return df


def _city_to_tier(city: str | float) -> str:
    if not isinstance(city, str):
        return "unknown"
    city_norm = city.lower()
    if "moscow" in city_norm or "моск" in city_norm:
        return "Moscow"
    if "spb" in city_norm or "петербург" in city_norm or "санкт" in city_norm:
        return "SPb"
    if city_norm in CITY_MILLION_PLUS:
        return "Million+"
    if any(country in city_norm for country in ["kazakhstan", "kazakh", "kz", "алматы", "нур-султан", "астана"]):
        return "KZ/Other"
    return "Other RU"


def add_city_tier(df: pd.DataFrame, city_col: str = "city") -> pd.DataFrame:
    """Map raw cities into simplified buckets for analysis."""
    if city_col in df.columns:
        df["city_tier"] = df[city_col].apply(_city_to_tier)
    else:
        df["city_tier"] = "unknown"
    return df


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _area_id(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fallback_city_name(value: str) -> str:
    normalized = " ".join(value.replace("\xa0", " ").split())
    return normalized[:100] if normalized else "unknown"


def _geo_from_city(city: Any, area_id: Any = None) -> tuple[str, str, str]:
    """Return normalized country, region and city for market segmentation."""

    resolved_area = _area_id(area_id)
    country, region, normalized_city = AREA_GEO_DEFAULTS.get(resolved_area, ("unknown", "unknown", "unknown"))
    raw_city = _normalize_text(city)
    city_lower = raw_city.lower()

    if city_lower:
        for alias_country, alias_region, alias_city, aliases in CITY_GEO_ALIASES:
            if any(alias in city_lower for alias in aliases):
                return alias_country, alias_region, alias_city

        for keyword_country, keywords in COUNTRY_KEYWORDS:
            if any(keyword in city_lower for keyword in keywords):
                country = keyword_country
                break

        if normalized_city == "unknown":
            normalized_city = _fallback_city_name(raw_city)

    return country, region, normalized_city


def _geo_scope_from_work_mode(work_mode: Any, is_remote: Any = None, is_hybrid: Any = None) -> str:
    mode = _normalize_text(work_mode).lower()
    if mode == "remote" or (isinstance(is_remote, (bool, np.bool_)) and bool(is_remote)):
        return "remote"
    if mode == "hybrid" or (isinstance(is_hybrid, (bool, np.bool_)) and bool(is_hybrid)):
        return "mixed"
    if mode in {"office", "field"}:
        return "local"
    return "unknown"


def add_geography_features(df: pd.DataFrame, city_col: str = "city") -> pd.DataFrame:
    """Normalize geography beyond city tier for local/remote market advice."""

    df = df.copy()
    cities = df[city_col] if city_col in df.columns else pd.Series(pd.NA, index=df.index)
    area_ids = df["search_area_id"] if "search_area_id" in df.columns else pd.Series(pd.NA, index=df.index)
    geo_rows = [_geo_from_city(city, area_id) for city, area_id in zip(cities, area_ids)]
    df["country"] = [row[0] for row in geo_rows]
    df["region"] = [row[1] for row in geo_rows]
    df["city_normalized"] = [row[2] for row in geo_rows]
    df["geo_scope"] = [
        _geo_scope_from_work_mode(
            df.get("work_mode").iloc[i] if "work_mode" in df else None,
            df.get("is_remote").iloc[i] if "is_remote" in df else None,
            df.get("is_hybrid").iloc[i] if "is_hybrid" in df else None,
        )
        for i in range(len(df))
    ]
    df["remote_geo_eligible"] = df["geo_scope"].isin({"remote", "mixed"}).astype("boolean")
    return df


def add_work_mode(df: pd.DataFrame) -> pd.DataFrame:
    """Create normalized work mode prioritizing explicit work_format, then remote/hybrid flags."""

    def decide(row: dict) -> str:
        work_format = row.get("work_format")
        if isinstance(work_format, str) and work_format in {"remote", "hybrid", "office", "field"}:
            return work_format
        remote_flag = row.get("is_remote")
        hybrid_flag = row.get("is_hybrid")
        if isinstance(remote_flag, (bool, np.bool_)) and remote_flag:
            return "remote"
        if isinstance(hybrid_flag, (bool, np.bool_)) and hybrid_flag:
            return "hybrid"
        return "unknown"

    df = df.copy()
    df["work_mode"] = [
        decide(
            {
                "is_remote": df.get("is_remote").iloc[i] if "is_remote" in df else None,
                "is_hybrid": df.get("is_hybrid").iloc[i] if "is_hybrid" in df else None,
                "work_format": df.get("work_format").iloc[i] if "work_format" in df else None,
            }
        )
        for i in range(len(df))
    ]
    return df


def add_experience_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Mark junior-friendly vacancies and their complement (battle experience)."""

    df = df.copy()
    junior_flags = [
        df[col].fillna(False)
        for col in ["is_for_juniors", "allows_students", "exp_is_no_experience"]
        if col in df.columns
    ]

    if junior_flags:
        df["is_junior_friendly"] = pd.concat(junior_flags, axis=1).any(axis=1).astype("boolean")
        df["battle_experience"] = (~df["is_junior_friendly"].fillna(False)).astype("boolean")
    return df


def add_boolean_counts(df: pd.DataFrame, groups: Dict[str, List[str]] | None = None) -> pd.DataFrame:
    """Aggregate boolean prefix groups into compact counters."""
    if groups is None:
        groups = detect_column_groups(df)

    mapping = {
        "benefit_": "benefits_count",
        "soft_": "soft_skills_count",
        "has_": "hard_stack_count",
        "skill_": "skills_count",
        "role_": "role_count",
    }

    for prefix, target_col in mapping.items():
        cols = groups.get(prefix, [])
        if cols:
            df[target_col] = df[cols].sum(axis=1)
    return df


def add_stack_aggregates(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate core data, ML stack, and overall tech stack sizes."""

    df = df.copy()

    def _count_true(columns: List[str]) -> pd.Series:
        if not columns:
            return pd.Series(0, index=df.index)
        return df[columns].fillna(False).astype(bool).astype(int).sum(axis=1)

    existing_core = [col for col in CORE_DATA_SKILLS if col in df.columns]
    existing_ml = [col for col in ML_STACK_SKILLS if col in df.columns]
    tech_cols = [col for col in df.columns if col.startswith("has_") or col.startswith("skill_")]

    df["core_data_skills_count"] = _count_true(existing_core)
    df["ml_stack_count"] = _count_true(existing_ml)
    df["tech_stack_size"] = _count_true(tech_cols)
    return df


def add_skill_stack_counts(df: pd.DataFrame, groups: Dict[str, List[str]] | None = None) -> pd.DataFrame:
    """Backward-compatible wrapper for stack aggregates."""

    return add_stack_aggregates(df)


def add_primary_role(df: pd.DataFrame, role_prefix: str = "role_") -> pd.DataFrame:
    """Collapse multiple role flags into a single prioritized primary role.

    Priority:
    1. Explicit role_* flags (in PRIMARY_ROLE_PRIORITY order)
    2. Fallback keyword matching over vacancy title (``title`` or legacy ``name``)
    3. ``other``
    """

    def _match_role_from_title(title: str | None) -> str | None:
        if not isinstance(title, str):
            return None
        lowered = title.lower()
        for role, keywords in PRIMARY_ROLE_KEYWORDS:
            if any(keyword in lowered for keyword in keywords):
                return role
        return None

    df = df.copy()
    primary_role: list[str] = []

    for _, row in df.iterrows():
        chosen = None
        for col in PRIMARY_ROLE_PRIORITY:
            if col in row and row[col]:
                chosen = col.replace(role_prefix, "")
                break

        if chosen is None:
            chosen = _match_role_from_title(row.get("title") or row.get("name"))

        primary_role.append(chosen or "other")

    df["primary_role"] = pd.Categorical(primary_role)
    return df


def add_salary_bucket(
    df: pd.DataFrame, salary_col: str = "salary_mid_rub_capped", labels: List[str] | None = None
) -> pd.DataFrame:
    """Create quantile-based salary buckets for downstream analysis."""
    if labels is None:
        labels = ["low", "mid", "high"]

    df = df.copy()
    if salary_col not in df.columns:
        df[salary_col] = np.nan

    valid = df[salary_col].dropna()
    if len(valid) >= len(labels):
        df.loc[valid.index, "salary_bucket"] = pd.qcut(valid, q=len(labels), labels=labels, duplicates="drop")
    else:
        df["salary_bucket"] = np.nan
    return df


def add_structured_text_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add targeted text features focused on the main description field."""

    df = df.copy()
    if "description" in df.columns:
        desc = df["description"].fillna("")
        df["description_len_chars"] = desc.str.len()
        df["description_len_words"] = desc.str.split().str.len()

    for col, target in [
        ("requirements", "requirements_count"),
        ("responsibilities", "responsibilities_count"),
        ("must_have_skills", "must_have_skills_count"),
        ("optional_skills", "optional_skills_count"),
    ]:
        if col in df.columns:
            df[target] = df[col].fillna("").str.split().str.len()
    return df


def compute_skill_premium(
    df: pd.DataFrame,
    skill_cols: Iterable[str],
    salary_col: str = "salary_mid_rub_capped",
    min_count: int = 30,
) -> pd.DataFrame:
    """Estimate salary premium for skills vs salary column."""
    records = []
    for col in skill_cols:
        if col not in df.columns:
            continue
        has_skill = df[col].fillna(False).astype(bool)
        count_with_skill = int(has_skill.sum())
        if count_with_skill < min_count:
            continue
        median_with = df.loc[has_skill, salary_col].median()
        median_without = df.loc[~has_skill, salary_col].median()
        premium_abs = median_with - median_without
        premium_pct = premium_abs / median_without if median_without else np.nan
        records.append(
            {
                "skill": col,
                "median_with": median_with,
                "median_without": median_without,
                "premium_abs": premium_abs,
                "premium_pct": premium_pct,
                "count_with_skill": count_with_skill,
            }
        )
    return pd.DataFrame(records).sort_values(by="premium_pct", ascending=False)


def ensure_expected_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Backfill core derived columns with safe defaults if missing."""

    expected_defaults = {
        "published_weekday": pd.NA,
        "country": "unknown",
        "region": "unknown",
        "city_normalized": "unknown",
        "geo_scope": "unknown",
        "remote_geo_eligible": pd.NA,
        "city_tier": "unknown",
        "work_mode": "unknown",
        "grade_from_experience": "unknown",
        "grade_final": "unknown",
        "primary_role": "other",
        "salary_bucket": pd.NA,
        "vacancy_age_days": pd.NA,
        "core_data_skills_count": 0,
        "ml_stack_count": 0,
        "tech_stack_size": 0,
        "benefits_count": 0,
        "soft_skills_count": 0,
        "role_count": 0,
        "is_junior_friendly": pd.NA,
        "battle_experience": pd.NA,
    }
    for col, default in expected_defaults.items():
        if col not in df.columns:
            df[col] = default
    return df


def assemble_features(df: pd.DataFrame) -> pd.DataFrame:
    """Convenience pipeline for feature dataframe."""
    grouped = detect_column_groups(df)
    df = add_time_features(df)
    df = add_city_tier(df)
    df = add_work_mode(df)
    df = add_geography_features(df)
    df = add_boolean_counts(df, groups=grouped)
    df = add_stack_aggregates(df)
    df = add_experience_flags(df)
    df = add_grade_from_experience(df)
    if "grade" in df.columns:
        df["grade_final"] = df["grade"].where(df["grade"] != "unknown", df["grade_from_experience"])
    else:
        df["grade_final"] = df["grade_from_experience"]
    df = add_primary_role(df)
    df = add_salary_bucket(df)
    df = add_structured_text_features(df)
    return ensure_expected_feature_columns(df)
