"""
Add lock and attempt columns to weekly subscriptions

Revision ID: 8b5bd17d6ce2
Revises: 5f5f0b8d5c0c
Create Date: 2025-02-20 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8b5bd17d6ce2"
down_revision = "5f5f0b8d5c0c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("weekly_subscriptions", sa.Column("lock", sa.String(length=64), nullable=True))
    op.add_column(
        "weekly_subscriptions",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("weekly_subscriptions", "attempt")
    op.drop_column("weekly_subscriptions", "lock")
