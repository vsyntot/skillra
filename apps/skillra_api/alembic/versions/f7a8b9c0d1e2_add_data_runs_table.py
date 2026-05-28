"""add data_runs table

Revision ID: f7a8b9c0d1e2
Revises: c9d0e1f2a3b4
Create Date: 2026-05-19 18:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
    )
    op.create_index("ix_data_runs_run_id", "data_runs", ["run_id"], unique=True)
    op.create_index("ix_data_runs_started_at", "data_runs", ["started_at"])
    op.create_index("ix_data_runs_state", "data_runs", ["state"])


def downgrade() -> None:
    op.drop_index("ix_data_runs_state", table_name="data_runs")
    op.drop_index("ix_data_runs_started_at", table_name="data_runs")
    op.drop_index("ix_data_runs_run_id", table_name="data_runs")
    op.drop_table("data_runs")
