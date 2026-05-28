"""add dataset registry control plane

Revision ID: 1b2c3d4e5f60
Revises: 0a1b2c3d4e5f
Create Date: 2026-05-26 19:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1b2c3d4e5f60"
down_revision: Union[str, None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("data_runs", sa.Column("dataset_meta_path", sa.Text(), nullable=True))
    op.add_column("data_runs", sa.Column("manifest_uri", sa.Text(), nullable=True))
    op.add_column("data_runs", sa.Column("quality_report_uri", sa.Text(), nullable=True))
    op.add_column("data_runs", sa.Column("artifact_uris", sa.JSON(), nullable=True))
    op.add_column("data_runs", sa.Column("raw_quality_report", sa.JSON(), nullable=True))
    op.add_column("data_runs", sa.Column("processed_quality_report", sa.JSON(), nullable=True))
    op.add_column("data_runs", sa.Column("product_eligibility", sa.JSON(), nullable=True))

    op.create_table(
        "active_datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("dataset_meta_path", sa.Text(), nullable=True),
        sa.Column("manifest_uri", sa.Text(), nullable=True),
        sa.Column("quality_report_uri", sa.Text(), nullable=True),
        sa.Column("raw_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["data_runs.run_id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_active_datasets_run_id", "active_datasets", ["run_id"])
    op.create_index("ix_active_datasets_activated_at", "active_datasets", ["activated_at"])
    op.execute(
        """
        INSERT INTO active_datasets (
            id,
            run_id,
            activated_at,
            source,
            dataset_meta_path,
            manifest_uri,
            quality_report_uri,
            raw_rows,
            processed_rows
        )
        SELECT
            1,
            run_id,
            COALESCE(finished_at, updated_at, started_at),
            source,
            dataset_meta_path,
            manifest_uri,
            quality_report_uri,
            raw_rows,
            processed_rows
        FROM data_runs
        WHERE state = 'published'
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """
    )


def downgrade() -> None:
    op.drop_index("ix_active_datasets_activated_at", table_name="active_datasets")
    op.drop_index("ix_active_datasets_run_id", table_name="active_datasets")
    op.drop_table("active_datasets")

    op.drop_column("data_runs", "product_eligibility")
    op.drop_column("data_runs", "processed_quality_report")
    op.drop_column("data_runs", "raw_quality_report")
    op.drop_column("data_runs", "artifact_uris")
    op.drop_column("data_runs", "quality_report_uri")
    op.drop_column("data_runs", "manifest_uri")
    op.drop_column("data_runs", "dataset_meta_path")
