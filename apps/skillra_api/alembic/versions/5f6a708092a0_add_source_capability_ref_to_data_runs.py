"""add source capability ref to data runs

Revision ID: 5f6a708092a0
Revises: 4e5f6a708091
Create Date: 2026-05-27 18:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5f6a708092a0"
down_revision: Union[str, None] = "4e5f6a708091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("data_runs", sa.Column("source_capability_ref", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("data_runs", "source_capability_ref")
