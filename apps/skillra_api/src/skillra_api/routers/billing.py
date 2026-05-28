"""Billing webhook endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from skillra_api.config import Settings
from skillra_api.deps import get_db_session, get_settings_dependency
from skillra_api.schemas import BillingWebhookOut, CommercialStateOut
from skillra_api.services.billing import (
    BILLING_SIGNATURE_HEADER,
    FakeBillingProviderAdapter,
    SignedSandboxBillingProviderAdapter,
    apply_billing_event,
    billing_state_payload,
)

router = APIRouter(prefix="/v1/billing", tags=["billing"])


@router.post("/webhooks/{provider}", response_model=BillingWebhookOut, response_class=JSONResponse)
async def handle_billing_webhook(
    provider: str,
    request: Request,
    signature: str | None = Header(default=None, alias=BILLING_SIGNATURE_HEADER),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings_dependency),
) -> BillingWebhookOut:
    """Accept a provider-neutral billing webhook.

    Non-fake providers are blocked in production until the explicit commercial
    launch flag is enabled.
    """

    adapter: FakeBillingProviderAdapter | SignedSandboxBillingProviderAdapter | None = None
    if provider == "fake" and settings.billing_fake_webhook_enabled:
        adapter = FakeBillingProviderAdapter(settings.billing_fake_webhook_secret)
    elif provider == settings.billing_sandbox_provider_name and settings.billing_sandbox_webhook_enabled:
        if settings.runtime_env == "prod" and not settings.billing_real_provider_launch_enabled:
            adapter = None
        else:
            adapter = SignedSandboxBillingProviderAdapter(
                settings.billing_sandbox_webhook_secret,
                provider=settings.billing_sandbox_provider_name,
            )

    if adapter is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "BILLING_PROVIDER_NOT_CONFIGURED",
                "message": "Billing provider is not configured.",
                "details": {"provider": provider},
            },
        )

    raw_body = await request.body()
    adapter.verify_webhook(raw_body, signature)
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BILLING_WEBHOOK_INVALID_JSON",
                "message": "Billing webhook body must be valid JSON.",
                "details": {"provider": provider},
            },
        ) from exc

    async with session.begin():
        event = adapter.parse_event(payload)
        account, duplicate, applied = await apply_billing_event(session, provider=adapter.provider, event=event)

    await session.refresh(account)
    return BillingWebhookOut(
        accepted=True,
        duplicate=duplicate,
        applied=applied,
        commercial_state=CommercialStateOut(**billing_state_payload(account)),
    )
