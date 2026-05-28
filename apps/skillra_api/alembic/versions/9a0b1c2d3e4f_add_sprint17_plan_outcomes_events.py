"""add sprint17 plan outcomes and product events

Revision ID: 9a0b1c2d3e4f
Revises: f8a9b0c1d2e3
Create Date: 2026-05-20 09:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9a0b1c2d3e4f"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vacancy_snapshots", sa.Column("dataset_run_id", sa.String(64), nullable=True))
    op.create_index("ix_vacancy_snapshots_dataset_run_id", "vacancy_snapshots", ["dataset_run_id"])
    op.add_column("indexer_runs", sa.Column("dataset_run_id", sa.String(64), nullable=True))
    op.create_index("ix_indexer_runs_dataset_run_id", "indexer_runs", ["dataset_run_id"])
    op.alter_column("indexer_runs", "source", existing_type=sa.String(32), type_=sa.String(64))

    op.add_column(
        "career_actions",
        sa.Column("recommendation_source", sa.String(32), server_default="manual", nullable=False),
    )
    op.add_column("career_actions", sa.Column("dataset_run_id", sa.String(64), nullable=True))
    op.add_column("career_actions", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("career_actions", sa.Column("expected_impact", sa.String(64), nullable=True))
    op.add_column("career_actions", sa.Column("effort_estimate", sa.String(64), nullable=True))
    op.add_column("career_actions", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("career_actions", sa.Column("evidence", sa.JSON(), nullable=True))
    op.add_column("career_actions", sa.Column("application_status", sa.String(32), nullable=True))
    op.create_index("ix_career_actions_dataset_run_id", "career_actions", ["dataset_run_id"])

    op.create_table(
        "application_outcome_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("career_actions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("hh_vacancy_id", sa.String(50), nullable=True),
        sa.Column("vacancy_title", sa.String(500), nullable=True),
        sa.Column("vacancy_url", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="user"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_application_outcomes_user_occurred",
        "application_outcome_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_application_outcomes_hh_vacancy_id",
        "application_outcome_events",
        ["hh_vacancy_id"],
    )

    op.create_table(
        "product_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="api"),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_product_events_user_type_occurred",
        "product_events",
        ["user_id", "event_type", "occurred_at"],
    )
    op.create_index("ix_product_events_event_type", "product_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_product_events_event_type", table_name="product_events")
    op.drop_index("ix_product_events_user_type_occurred", table_name="product_events")
    op.drop_table("product_events")
    op.drop_index("ix_application_outcomes_hh_vacancy_id", table_name="application_outcome_events")
    op.drop_index("ix_application_outcomes_user_occurred", table_name="application_outcome_events")
    op.drop_table("application_outcome_events")
    op.drop_index("ix_career_actions_dataset_run_id", table_name="career_actions")
    op.drop_column("career_actions", "application_status")
    op.drop_column("career_actions", "evidence")
    op.drop_column("career_actions", "due_date")
    op.drop_column("career_actions", "effort_estimate")
    op.drop_column("career_actions", "expected_impact")
    op.drop_column("career_actions", "reason")
    op.drop_column("career_actions", "dataset_run_id")
    op.drop_column("career_actions", "recommendation_source")
    op.alter_column("indexer_runs", "source", existing_type=sa.String(64), type_=sa.String(32))
    op.drop_index("ix_indexer_runs_dataset_run_id", table_name="indexer_runs")
    op.drop_column("indexer_runs", "dataset_run_id")
    op.drop_index("ix_vacancy_snapshots_dataset_run_id", table_name="vacancy_snapshots")
    op.drop_column("vacancy_snapshots", "dataset_run_id")
