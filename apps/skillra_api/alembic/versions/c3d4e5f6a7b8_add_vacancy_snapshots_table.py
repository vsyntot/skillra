"""add vacancy_snapshots table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-13 10:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vacancy_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hh_vacancy_id", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("primary_role", sa.String(100), nullable=True),
        sa.Column("grade", sa.String(50), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("city_tier", sa.String(50), nullable=True),
        sa.Column("salary_from", sa.Integer(), nullable=True),
        sa.Column("salary_to", sa.Integer(), nullable=True),
        sa.Column("description_snippet", sa.String(1000), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # skills column — use ARRAY for postgres, JSON for sqlite
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.add_column(
            "vacancy_snapshots",
            sa.Column("skills", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"),
        )
    else:
        op.add_column(
            "vacancy_snapshots",
            sa.Column("skills", sa.JSON(), nullable=False, server_default="[]"),
        )

    op.create_index("ix_vacancy_snapshots_hh_vacancy_id", "vacancy_snapshots", ["hh_vacancy_id"])
    op.create_index("ix_vacancy_snapshots_role_grade", "vacancy_snapshots", ["primary_role", "grade"])
    op.create_index("ix_vacancy_snapshots_published_at", "vacancy_snapshots", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_vacancy_snapshots_published_at", table_name="vacancy_snapshots")
    op.drop_index("ix_vacancy_snapshots_role_grade", table_name="vacancy_snapshots")
    op.drop_index("ix_vacancy_snapshots_hh_vacancy_id", table_name="vacancy_snapshots")
    op.drop_table("vacancy_snapshots")
