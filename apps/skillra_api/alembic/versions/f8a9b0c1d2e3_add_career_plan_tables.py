"""add career plan tables

Revision ID: f8a9b0c1d2e3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-19 19:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "career_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_role", sa.String(100), nullable=True),
        sa.Column("target_grade", sa.String(50), nullable=True),
        sa.Column("target_city_tier", sa.String(50), nullable=True),
        sa.Column("target_work_mode", sa.String(50), nullable=True),
        sa.Column("target_domain", sa.String(100), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_career_plans_user_id", "career_plans", ["user_id"], unique=True)
    op.create_index("ix_career_plans_status", "career_plans", ["status"])

    op.create_table(
        "career_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("career_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("action_type", sa.String(32), nullable=False, server_default="learning"),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("skill_name", sa.String(100), nullable=True),
        sa.Column("hh_vacancy_id", sa.String(50), nullable=True),
        sa.Column("vacancy_title", sa.String(500), nullable=True),
        sa.Column("vacancy_url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_career_actions_plan_id_status", "career_actions", ["plan_id", "status"])
    op.create_index("ix_career_actions_hh_vacancy_id", "career_actions", ["hh_vacancy_id"])


def downgrade() -> None:
    op.drop_index("ix_career_actions_hh_vacancy_id", table_name="career_actions")
    op.drop_index("ix_career_actions_plan_id_status", table_name="career_actions")
    op.drop_table("career_actions")
    op.drop_index("ix_career_plans_status", table_name="career_plans")
    op.drop_index("ix_career_plans_user_id", table_name="career_plans")
    op.drop_table("career_plans")
