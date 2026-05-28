import sqlalchemy as sa
from skillra_api.db import (
    Base,
    models,  # noqa: F401  # ensure models are imported
)


def test_metadata_contains_expected_tables() -> None:
    table_names = set(Base.metadata.tables.keys())
    assert {
        "users",
        "user_profiles",
        "weekly_subscriptions",
        "market_snapshots",
        "user_resumes",
        "career_plans",
        "career_actions",
        "data_runs",
    }.issubset(table_names)


def test_users_has_unique_telegram_user_id() -> None:
    users = Base.metadata.tables["users"]
    telegram_constraints = [
        constraint
        for constraint in users.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and {col.name for col in constraint.columns} == {"telegram_user_id"}
    ]
    assert telegram_constraints


def test_weekly_subscriptions_indexes_and_constraints() -> None:
    weekly = Base.metadata.tables["weekly_subscriptions"]
    index_names = {index.name for index in weekly.indexes}
    assert "ix_weekly_subscriptions_active_weekday" in index_names

    weekday_checks = [
        constraint
        for constraint in weekly.constraints
        if isinstance(constraint, sa.CheckConstraint) and "weekday" in str(constraint.sqltext)
    ]
    assert weekday_checks
