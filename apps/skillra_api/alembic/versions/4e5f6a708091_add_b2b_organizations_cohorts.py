"""add b2b organizations and cohorts

Revision ID: 4e5f6a708091
Revises: 3d4e5f6a7080
Create Date: 2026-05-27 16:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4e5f6a708091"
down_revision: Union[str, None] = "3d4e5f6a7080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("organization_type", sa.String(32), nullable=False, server_default="other"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "organization_type IN ('university', 'bootcamp', 'career_center', 'company', 'other')",
            name="ck_organizations_type",
        ),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_index("ix_organizations_archived_at", "organizations", ["archived_at"])

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_organization_memberships_role"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_organization_memberships_status"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_memberships_org_user"),
    )
    op.create_index(
        "ix_organization_memberships_user_status",
        "organization_memberships",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_organization_memberships_org_role",
        "organization_memberships",
        ["organization_id", "role"],
    )

    op.create_table(
        "cohorts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("starts_at", sa.Date(), nullable=True),
        sa.Column("ends_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_cohorts_org_slug"),
    )
    op.create_index("ix_cohorts_organization_archived", "cohorts", ["organization_id", "archived_at"])

    op.create_table(
        "cohort_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cohort_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_cohort_memberships_status"),
        sa.UniqueConstraint("cohort_id", "user_id", name="uq_cohort_memberships_cohort_user"),
    )
    op.create_index("ix_cohort_memberships_user_status", "cohort_memberships", ["user_id", "status"])

    op.create_table(
        "organization_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("cohort_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("uses_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_organization_invites_role"),
        sa.CheckConstraint("max_uses >= 1", name="ck_organization_invites_max_uses"),
        sa.CheckConstraint("uses_count >= 0", name="ck_organization_invites_uses_count"),
        sa.UniqueConstraint("token_hash", name="uq_organization_invites_token_hash"),
    )
    op.create_index(
        "ix_organization_invites_org_revoked",
        "organization_invites",
        ["organization_id", "revoked_at"],
    )
    op.create_index("ix_organization_invites_expires_at", "organization_invites", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_organization_invites_expires_at", table_name="organization_invites")
    op.drop_index("ix_organization_invites_org_revoked", table_name="organization_invites")
    op.drop_table("organization_invites")
    op.drop_index("ix_cohort_memberships_user_status", table_name="cohort_memberships")
    op.drop_table("cohort_memberships")
    op.drop_index("ix_cohorts_organization_archived", table_name="cohorts")
    op.drop_table("cohorts")
    op.drop_index("ix_organization_memberships_org_role", table_name="organization_memberships")
    op.drop_index("ix_organization_memberships_user_status", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_index("ix_organizations_archived_at", table_name="organizations")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
