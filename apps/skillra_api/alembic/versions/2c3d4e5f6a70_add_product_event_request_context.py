"""add product event request context

Revision ID: 2c3d4e5f6a70
Revises: 1b2c3d4e5f60
Create Date: 2026-05-27 12:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2c3d4e5f6a70"
down_revision: Union[str, None] = "1b2c3d4e5f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("product_events", sa.Column("request_id", sa.String(128), nullable=True))
    op.add_column("product_events", sa.Column("session_id", sa.String(128), nullable=True))
    op.add_column("product_events", sa.Column("correlation_id", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("product_events", "correlation_id")
    op.drop_column("product_events", "session_id")
    op.drop_column("product_events", "request_id")
