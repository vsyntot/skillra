"""add sprint17 geography contract

Revision ID: 0a1b2c3d4e5f
Revises: 9a0b1c2d3e4f
Create Date: 2026-05-20 14:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, None] = "9a0b1c2d3e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("user_profiles", "career_plans"):
        op.add_column(table_name, sa.Column("target_country", sa.String(100), nullable=True))
        op.add_column(table_name, sa.Column("target_region", sa.String(100), nullable=True))
        op.add_column(table_name, sa.Column("target_city", sa.String(100), nullable=True))
        op.add_column(table_name, sa.Column("target_geo_scope", sa.String(32), nullable=True))

    op.add_column("vacancy_snapshots", sa.Column("country", sa.String(100), nullable=True))
    op.add_column("vacancy_snapshots", sa.Column("region", sa.String(100), nullable=True))
    op.add_column("vacancy_snapshots", sa.Column("city_normalized", sa.String(100), nullable=True))
    op.add_column("vacancy_snapshots", sa.Column("geo_scope", sa.String(32), nullable=True))
    op.create_index(
        "ix_vacancy_snapshots_geo",
        "vacancy_snapshots",
        ["country", "region", "city_normalized"],
    )


def downgrade() -> None:
    op.drop_index("ix_vacancy_snapshots_geo", table_name="vacancy_snapshots")
    op.drop_column("vacancy_snapshots", "geo_scope")
    op.drop_column("vacancy_snapshots", "city_normalized")
    op.drop_column("vacancy_snapshots", "region")
    op.drop_column("vacancy_snapshots", "country")

    for table_name in ("career_plans", "user_profiles"):
        op.drop_column(table_name, "target_geo_scope")
        op.drop_column(table_name, "target_city")
        op.drop_column(table_name, "target_region")
        op.drop_column(table_name, "target_country")
