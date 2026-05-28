"""add digest_history table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-29 10:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "digest_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("format", sa.String(20), nullable=False, server_default="HTML"),
        sa.Column("text_preview", sa.String(500), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_digest_history_user_id", "digest_history", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_digest_history_user_id", table_name="digest_history")
    op.drop_table("digest_history")
