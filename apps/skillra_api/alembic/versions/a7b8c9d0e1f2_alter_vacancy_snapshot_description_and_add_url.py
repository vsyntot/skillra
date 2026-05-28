"""alter vacancy snapshot description and add hh_url

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-19 12:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "vacancy_snapshots",
        "description_snippet",
        existing_type=sa.String(1000),
        type_=sa.String(5000),
        existing_nullable=True,
    )
    op.add_column("vacancy_snapshots", sa.Column("hh_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("vacancy_snapshots", "hh_url")
    op.alter_column(
        "vacancy_snapshots",
        "description_snippet",
        existing_type=sa.String(5000),
        type_=sa.String(1000),
        existing_nullable=True,
    )
