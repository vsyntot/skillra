"""add backoff_until to weekly_subscriptions

Revision ID: a1b2c3d4e5f6
Revises: 8b5bd17d6ce2
Create Date: 2026-06-15 10:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "8b5bd17d6ce2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "weekly_subscriptions",
        sa.Column("backoff_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("weekly_subscriptions", "backoff_until")
