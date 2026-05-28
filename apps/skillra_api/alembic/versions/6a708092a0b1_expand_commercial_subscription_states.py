"""expand commercial subscription states

Revision ID: 6a708092a0b1
Revises: 5f6a708092a0
Create Date: 2026-05-28 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "6a708092a0b1"
down_revision: Union[str, None] = "5f6a708092a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATES = "'none', 'trialing', 'active', 'past_due', 'cancelled'"
NEW_STATES = (
    "'none', 'trialing', 'active', 'cancel_at_period_end', 'expired', 'refunded', "
    "'payment_failed', 'provider_unavailable', 'past_due', 'cancelled'"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_user_commercial_accounts_subscription_state",
            "user_commercial_accounts",
            type_="check",
        )
        op.create_check_constraint(
            "ck_user_commercial_accounts_subscription_state",
            "user_commercial_accounts",
            f"subscription_state IN ({NEW_STATES})",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "UPDATE user_commercial_accounts "
            "SET subscription_state = 'past_due' "
            "WHERE subscription_state IN ('payment_failed', 'provider_unavailable')"
        )
        op.execute(
            "UPDATE user_commercial_accounts "
            "SET subscription_state = 'cancelled' "
            "WHERE subscription_state IN ('cancel_at_period_end', 'expired', 'refunded')"
        )
        op.drop_constraint(
            "ck_user_commercial_accounts_subscription_state",
            "user_commercial_accounts",
            type_="check",
        )
        op.create_check_constraint(
            "ck_user_commercial_accounts_subscription_state",
            "user_commercial_accounts",
            f"subscription_state IN ({OLD_STATES})",
        )
