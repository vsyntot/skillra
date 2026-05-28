"""add commercial entitlements

Revision ID: 3d4e5f6a7080
Revises: 2c3d4e5f6a70
Create Date: 2026-05-27 15:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3d4e5f6a7080"
down_revision: Union[str, None] = "2c3d4e5f6a70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_commercial_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        sa.Column("subscription_state", sa.String(32), nullable=False, server_default="none"),
        sa.Column("entitlements", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("provider_customer_id", sa.String(128), nullable=True),
        sa.Column("provider_subscription_id", sa.String(128), nullable=True),
        sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("plan IN ('free', 'trial', 'pro', 'admin')", name="ck_user_commercial_accounts_plan"),
        sa.CheckConstraint(
            "subscription_state IN ('none', 'trialing', 'active', 'past_due', 'cancelled')",
            name="ck_user_commercial_accounts_subscription_state",
        ),
        sa.UniqueConstraint("user_id", name="uq_user_commercial_accounts_user_id"),
    )
    op.create_index(
        "ix_user_commercial_accounts_plan_state",
        "user_commercial_accounts",
        ["plan", "subscription_state"],
    )

    op.create_table(
        "billing_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_billing_events_provider_event"),
    )
    op.create_index("ix_billing_events_user_id", "billing_events", ["user_id"])
    op.create_index("ix_billing_events_user_provider", "billing_events", ["user_id", "provider"])


def downgrade() -> None:
    op.drop_index("ix_billing_events_user_provider", table_name="billing_events")
    op.drop_index("ix_billing_events_user_id", table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_index("ix_user_commercial_accounts_plan_state", table_name="user_commercial_accounts")
    op.drop_table("user_commercial_accounts")
