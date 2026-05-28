"""add market_snapshots table

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-19 13:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("grade", sa.String(50), nullable=False),
        sa.Column("city_tier", sa.String(50), nullable=False),
        sa.Column("work_mode", sa.String(50), nullable=False),
        sa.Column("domain", sa.String(100), nullable=False),
        sa.Column("vacancy_count", sa.Integer(), nullable=False),
        sa.Column("salary_p25", sa.Float(), nullable=True),
        sa.Column("salary_p50", sa.Float(), nullable=True),
        sa.Column("salary_p75", sa.Float(), nullable=True),
        sa.Column("skill_top10", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "week_start",
            "role",
            "grade",
            "city_tier",
            "work_mode",
            "domain",
            name="uq_market_snapshots_segment_week",
        ),
    )
    op.create_index("ix_market_snapshots_week_start", "market_snapshots", ["week_start"])
    op.create_index("ix_market_snapshots_role_grade_week", "market_snapshots", ["role", "grade", "week_start"])


def downgrade() -> None:
    op.drop_index("ix_market_snapshots_role_grade_week", table_name="market_snapshots")
    op.drop_index("ix_market_snapshots_week_start", table_name="market_snapshots")
    op.drop_table("market_snapshots")
