"""Market snapshot persistence and trend helpers."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
from skillra_api.db.models import MarketSnapshot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def upsert_snapshots(session: AsyncSession, snapshots_df: pd.DataFrame) -> int:
    """Upsert weekly market snapshots from a dataframe into the database."""

    if snapshots_df.empty:
        return 0

    changed = 0
    for row in snapshots_df[SNAPSHOT_COLUMNS].to_dict(orient="records"):
        payload = _normalize_snapshot_row(row)
        existing = await session.scalar(
            select(MarketSnapshot).where(
                MarketSnapshot.week_start == payload["week_start"],
                MarketSnapshot.role == payload["role"],
                MarketSnapshot.grade == payload["grade"],
                MarketSnapshot.city_tier == payload["city_tier"],
                MarketSnapshot.work_mode == payload["work_mode"],
                MarketSnapshot.domain == payload["domain"],
            )
        )
        if existing is None:
            session.add(MarketSnapshot(**payload))
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
        changed += 1

    await session.commit()
    return changed


async def load_snapshots_df(session: AsyncSession) -> pd.DataFrame:
    """Load all market snapshots from DB as a dataframe."""

    rows = (await session.scalars(select(MarketSnapshot).order_by(MarketSnapshot.week_start, MarketSnapshot.id))).all()
    return snapshots_to_frame(list(rows))


def snapshots_to_frame(rows: list[MarketSnapshot]) -> pd.DataFrame:
    """Convert ORM rows into the dataframe shape used by core timeseries helpers."""

    return pd.DataFrame(
        [
            {
                "week_start": row.week_start,
                "role": row.role,
                "grade": row.grade,
                "city_tier": row.city_tier,
                "work_mode": row.work_mode,
                "domain": row.domain,
                "vacancy_count": row.vacancy_count,
                "salary_p25": row.salary_p25,
                "salary_p50": row.salary_p50,
                "salary_p75": row.salary_p75,
                "skill_top10": _skill_list(row.skill_top10),
            }
            for row in rows
        ]
    )


def _normalize_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
    week_start = row["week_start"]
    if not isinstance(week_start, date):
        week_start = pd.Timestamp(week_start).date()

    skills = row.get("skill_top10")
    if isinstance(skills, str):
        skill_top10 = skills
    elif isinstance(skills, list):
        skill_top10 = json.dumps([str(skill) for skill in skills])
    else:
        skill_top10 = None

    return {
        "week_start": week_start,
        "role": str(row["role"]),
        "grade": str(row["grade"]),
        "city_tier": str(row["city_tier"]),
        "work_mode": str(row["work_mode"]),
        "domain": str(row["domain"]),
        "vacancy_count": int(row["vacancy_count"] or 0),
        "salary_p25": _float_or_none(row.get("salary_p25")),
        "salary_p50": _float_or_none(row.get("salary_p50")),
        "salary_p75": _float_or_none(row.get("salary_p75")),
        "skill_top10": skill_top10,
    }


def _skill_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
