"""Commercial plan, entitlement and locked-state helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from skillra_api.db.models import User, UserCommercialAccount
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

COMMERCIAL_PLANS = {"free", "trial", "pro", "admin"}
COMMERCIAL_SUBSCRIPTION_STATES = {
    "none",
    "trialing",
    "active",
    "cancel_at_period_end",
    "expired",
    "refunded",
    "payment_failed",
    "provider_unavailable",
    "past_due",
    "cancelled",
}
ENTITLEMENT_GRANTING_STATES = {"trialing", "active", "cancel_at_period_end"}
STATE_ALIASES = {"payment_failed": "payment_failed", "failed": "payment_failed", "past_due": "payment_failed"}

ENTITLEMENT_PROFILE_BASIC = "profile.basic"
ENTITLEMENT_MARKET_BASIC = "market.basic"
ENTITLEMENT_VACANCY_SEARCH_BASIC = "vacancy_search.basic"
ENTITLEMENT_DIGEST_BASIC = "digest.basic"
ENTITLEMENT_CAREER_PLAN_BASIC = "career_plan.basic"
ENTITLEMENT_CAREER_PLAN_GENERATE = "career_plan.generate_actions"
ENTITLEMENT_SKILL_GAP_EXPORT = "skill_gap.export"
ENTITLEMENT_TRENDS_ADVANCED = "trends.advanced"

PLAN_ENTITLEMENTS: dict[str, set[str]] = {
    "free": {
        ENTITLEMENT_PROFILE_BASIC,
        ENTITLEMENT_MARKET_BASIC,
        ENTITLEMENT_VACANCY_SEARCH_BASIC,
        ENTITLEMENT_DIGEST_BASIC,
        ENTITLEMENT_CAREER_PLAN_BASIC,
    },
    "trial": {
        ENTITLEMENT_PROFILE_BASIC,
        ENTITLEMENT_MARKET_BASIC,
        ENTITLEMENT_VACANCY_SEARCH_BASIC,
        ENTITLEMENT_DIGEST_BASIC,
        ENTITLEMENT_CAREER_PLAN_BASIC,
        ENTITLEMENT_CAREER_PLAN_GENERATE,
        ENTITLEMENT_SKILL_GAP_EXPORT,
        ENTITLEMENT_TRENDS_ADVANCED,
    },
    "pro": {
        ENTITLEMENT_PROFILE_BASIC,
        ENTITLEMENT_MARKET_BASIC,
        ENTITLEMENT_VACANCY_SEARCH_BASIC,
        ENTITLEMENT_DIGEST_BASIC,
        ENTITLEMENT_CAREER_PLAN_BASIC,
        ENTITLEMENT_CAREER_PLAN_GENERATE,
        ENTITLEMENT_SKILL_GAP_EXPORT,
        ENTITLEMENT_TRENDS_ADVANCED,
    },
    "admin": {"*"},
}

PREMIUM_FEATURES = {
    ENTITLEMENT_CAREER_PLAN_GENERATE,
    ENTITLEMENT_SKILL_GAP_EXPORT,
    ENTITLEMENT_TRENDS_ADVANCED,
}

FEATURE_LOCKED_COPY = {
    ENTITLEMENT_CAREER_PLAN_GENERATE: (
        "Генерация действий из skill gap доступна в пробном или Pro-плане. "
        "Откройте раздел Аккаунт, чтобы проверить доступ."
    ),
    ENTITLEMENT_SKILL_GAP_EXPORT: "Экспорт skill gap доступен в Pro-плане.",
    ENTITLEMENT_TRENDS_ADVANCED: "Расширенные тренды доступны в Pro-плане.",
}


def normalize_plan(value: str | None) -> str:
    normalized = str(value or "free").strip().lower()
    return normalized if normalized in COMMERCIAL_PLANS else "free"


def normalize_subscription_state(value: str | None, *, plan: str) -> str:
    normalized = STATE_ALIASES.get(str(value or "").strip().lower(), str(value or "").strip().lower())
    if normalized in COMMERCIAL_SUBSCRIPTION_STATES:
        return normalized
    if plan == "trial":
        return "trialing"
    if plan in {"pro", "admin"}:
        return "active"
    return "none"


def entitlements_for_plan(plan: str) -> list[str]:
    entitlements = PLAN_ENTITLEMENTS.get(normalize_plan(plan), PLAN_ENTITLEMENTS["free"])
    if "*" in entitlements:
        return sorted(PREMIUM_FEATURES | PLAN_ENTITLEMENTS["pro"] | {"*"})
    return sorted(entitlements)


def resolve_entitlements(account: UserCommercialAccount) -> list[str]:
    state = normalize_subscription_state(account.subscription_state, plan=account.plan)
    if normalize_plan(account.plan) != "admin" and state not in ENTITLEMENT_GRANTING_STATES:
        return entitlements_for_plan("free")
    if isinstance(account.entitlements, list) and account.entitlements:
        return sorted({str(item) for item in account.entitlements if str(item).strip()})
    return entitlements_for_plan(account.plan)


def has_entitlement(account: UserCommercialAccount, entitlement: str) -> bool:
    entitlements = set(resolve_entitlements(account))
    return "*" in entitlements or entitlement in entitlements


def locked_features(account: UserCommercialAccount) -> list[str]:
    entitlements = set(resolve_entitlements(account))
    if "*" in entitlements:
        return []
    return sorted(PREMIUM_FEATURES - entitlements)


async def get_or_create_commercial_account(
    session: AsyncSession,
    user: User,
    *,
    plan: str = "free",
    subscription_state: str | None = None,
) -> UserCommercialAccount:
    account = await session.scalar(select(UserCommercialAccount).where(UserCommercialAccount.user_id == user.id))
    if account is not None:
        return account

    normalized_plan = normalize_plan(plan)
    account = UserCommercialAccount(
        user_id=user.id,
        plan=normalized_plan,
        subscription_state=normalize_subscription_state(subscription_state, plan=normalized_plan),
        entitlements=entitlements_for_plan(normalized_plan),
    )
    session.add(account)
    await session.flush()
    return account


def commercial_state_payload(account: UserCommercialAccount) -> dict[str, Any]:
    return {
        "plan": normalize_plan(account.plan),
        "subscription_state": normalize_subscription_state(account.subscription_state, plan=account.plan),
        "entitlements": resolve_entitlements(account),
        "locked_features": locked_features(account),
        "trial_ends_at": account.trial_ends_at,
        "current_period_ends_at": account.current_period_ends_at,
        "provider": account.provider,
        "account_url": "/account",
    }


async def ensure_user_entitlement(
    session: AsyncSession,
    user: User,
    entitlement: str,
) -> UserCommercialAccount:
    account = await get_or_create_commercial_account(session, user)
    if has_entitlement(account, entitlement):
        return account
    raise HTTPException(
        status_code=402,
        detail={
            "error_code": "ENTITLEMENT_REQUIRED",
            "message": FEATURE_LOCKED_COPY.get(entitlement, "Эта возможность доступна в Pro-плане."),
            "details": {
                "feature": entitlement,
                "plan": normalize_plan(account.plan),
                "required_plans": ["trial", "pro", "admin"],
                "account_url": "/account",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        },
    )
