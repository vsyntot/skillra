"""create user profile and subscription tables

Revision ID: 5f5f0b8d5c0c
Revises:
Create Date: 2024-07-06 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "5f5f0b8d5c0c"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_users_telegram_user_id")),
    )
    op.create_index(op.f("ix_users_telegram_user_id"), "users", ["telegram_user_id"], unique=False)

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_role", sa.String(length=100), nullable=True),
        sa.Column("target_grade", sa.String(length=50), nullable=True),
        sa.Column("target_city_tier", sa.String(length=50), nullable=True),
        sa.Column("target_work_mode", sa.String(length=50), nullable=True),
        sa.Column("target_domain", sa.String(length=100), nullable=True),
        sa.Column(
            "current_skills",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("ARRAY[]::varchar[]"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=op.f("fk_user_profiles_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profiles")),
        sa.UniqueConstraint("user_id", name=op.f("uq_user_profiles_user_id")),
    )

    op.create_table(
        "weekly_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("time_local", sa.String(length=5), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name=op.f("ck_weekly_subscriptions_weekday_range")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=op.f("fk_weekly_subscriptions_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_subscriptions")),
        sa.UniqueConstraint("user_id", name=op.f("uq_weekly_subscriptions_user_id")),
    )
    op.create_index(
        op.f("ix_weekly_subscriptions_active_weekday"),
        "weekly_subscriptions",
        ["active", "weekday"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_weekly_subscriptions_active_weekday"), table_name="weekly_subscriptions")
    op.drop_table("weekly_subscriptions")
    op.drop_table("user_profiles")
    op.drop_index(op.f("ix_users_telegram_user_id"), table_name="users")
    op.drop_table("users")
