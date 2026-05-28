"""Provider-neutral billing webhook boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from fastapi import HTTPException
from skillra_api.db.models import BillingEvent, User, UserCommercialAccount
from skillra_api.schemas import BillingFakeWebhookIn
from skillra_api.services.commercial import (
    commercial_state_payload,
    entitlements_for_plan,
    normalize_plan,
    normalize_subscription_state,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BILLING_SIGNATURE_HEADER = "X-Skillra-Billing-Signature"


@dataclass(frozen=True)
class BillingEventPayload:
    provider_event_id: str
    event_type: str
    telegram_user_id: int
    plan: str
    subscription_state: str
    entitlements: list[str] | None
    provider_customer_id: str | None
    provider_subscription_id: str | None
    trial_ends_at: datetime | None
    current_period_ends_at: datetime | None
    occurred_at: datetime | None
    raw_payload: dict[str, Any]


class BillingProviderAdapter(Protocol):
    """Adapter contract for billing providers.

    Implementations must verify webhook authenticity before parsing events.
    Production adapters should use provider signatures and idempotent event ids.
    """

    provider: str

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> None:
        """Raise HTTPException if the webhook signature is invalid."""

    def parse_event(self, payload: dict[str, Any]) -> BillingEventPayload:
        """Return a provider-neutral billing event."""


class FakeBillingProviderAdapter:
    """Local/CI fake billing adapter with deterministic HMAC verification."""

    provider = "fake"

    def __init__(self, secret: str, *, provider: str | None = None) -> None:
        self._secret = secret.encode()
        if provider:
            self.provider = provider

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> None:
        expected = hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "BILLING_WEBHOOK_SIGNATURE_INVALID",
                    "message": "Invalid billing webhook signature.",
                    "details": {"provider": self.provider},
                },
            )

    def parse_event(self, payload: dict[str, Any]) -> BillingEventPayload:
        event = BillingFakeWebhookIn.model_validate(payload)
        plan = normalize_plan(event.plan)
        return BillingEventPayload(
            provider_event_id=event.event_id,
            event_type=event.event_type,
            telegram_user_id=event.telegram_user_id,
            plan=plan,
            subscription_state=normalize_subscription_state(event.subscription_state, plan=plan),
            entitlements=event.entitlements,
            provider_customer_id=event.provider_customer_id,
            provider_subscription_id=event.provider_subscription_id,
            trial_ends_at=event.trial_ends_at,
            current_period_ends_at=event.current_period_ends_at,
            occurred_at=event.occurred_at,
            raw_payload=payload,
        )


class SignedSandboxBillingProviderAdapter(FakeBillingProviderAdapter):
    """Signed staging/manual-invoice adapter behind the provider-neutral boundary."""

    provider = "manual_invoice"


def _parse_event_occurred_at(payload: dict[str, Any] | None) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("occurred_at")
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _latest_subscription_event_occurred_at(
    session: AsyncSession,
    *,
    user_id: int,
    provider: str,
    provider_subscription_id: str | None,
) -> datetime | None:
    if not provider_subscription_id:
        return None
    rows = await session.scalars(
        select(BillingEvent)
        .where(BillingEvent.user_id == user_id, BillingEvent.provider == provider)
        .order_by(BillingEvent.processed_at.desc(), BillingEvent.id.desc())
    )
    latest: datetime | None = None
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        if payload.get("provider_subscription_id") != provider_subscription_id:
            continue
        occurred_at = _parse_event_occurred_at(payload)
        if occurred_at and (latest is None or occurred_at > latest):
            latest = occurred_at
    return latest


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def fake_billing_signature(payload: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), canonical_json_bytes(payload), hashlib.sha256).hexdigest()


async def apply_billing_event(
    session: AsyncSession,
    *,
    provider: str,
    event: BillingEventPayload,
) -> tuple[UserCommercialAccount, bool, bool]:
    existing = await session.scalar(
        select(BillingEvent).where(
            BillingEvent.provider == provider,
            BillingEvent.provider_event_id == event.provider_event_id,
        )
    )
    user = await session.scalar(select(User).where(User.telegram_user_id == event.telegram_user_id))
    if user is None:
        user = User(telegram_user_id=event.telegram_user_id)
        session.add(user)
        await session.flush()

    account = await session.scalar(select(UserCommercialAccount).where(UserCommercialAccount.user_id == user.id))
    if account is None:
        account = UserCommercialAccount(user_id=user.id)
        session.add(account)

    if existing is not None:
        return account, True, False

    latest_occurred_at = await _latest_subscription_event_occurred_at(
        session,
        user_id=user.id,
        provider=provider,
        provider_subscription_id=event.provider_subscription_id,
    )
    is_out_of_order = bool(event.occurred_at and latest_occurred_at and event.occurred_at < latest_occurred_at)
    if is_out_of_order:
        session.add(
            BillingEvent(
                user_id=user.id,
                provider=provider,
                provider_event_id=event.provider_event_id,
                event_type=event.event_type,
                payload={**event.raw_payload, "ignored_reason": "out_of_order"},
                processed_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()
        return account, False, False

    account.plan = event.plan
    account.subscription_state = event.subscription_state
    account.entitlements = event.entitlements or entitlements_for_plan(event.plan)
    account.provider = provider
    account.provider_customer_id = event.provider_customer_id
    account.provider_subscription_id = event.provider_subscription_id
    account.trial_ends_at = event.trial_ends_at
    account.current_period_ends_at = event.current_period_ends_at
    if event.plan == "trial" and account.trial_started_at is None:
        account.trial_started_at = datetime.now(timezone.utc)

    session.add(
        BillingEvent(
            user_id=user.id,
            provider=provider,
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            payload=event.raw_payload,
            processed_at=datetime.now(timezone.utc),
        )
    )
    await session.flush()
    return account, False, True


def billing_state_payload(account: UserCommercialAccount) -> dict[str, Any]:
    return commercial_state_payload(account)
