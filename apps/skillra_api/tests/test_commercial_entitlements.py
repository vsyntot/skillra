from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from skillra_api.config import Settings
from skillra_api.db import Base
from skillra_api.main import create_app
from skillra_api.services.billing import canonical_json_bytes, fake_billing_signature


async def _prepare_database(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture()
def commercial_client(
    tmp_path: Path, service_token: str, auth_headers: dict[str, str]
) -> Generator[TestClient, None, None]:
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'commercial.db'}",
        billing_fake_webhook_enabled=True,
        billing_fake_webhook_secret="test-fake-billing-secret",
    )
    app = create_app(settings)
    engine = app.state.db_engine

    with TestClient(app) as client:
        client.portal.call(_prepare_database, engine)
        client.headers.update(auth_headers)
        yield client


def test_default_commercial_state_is_free_and_locks_premium_features(commercial_client: TestClient) -> None:
    response = commercial_client.get("/v1/users/701/commercial-state")

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "free"
    assert body["subscription_state"] == "none"
    assert "career_plan.generate_actions" in body["locked_features"]
    assert "skill_gap.export" in body["locked_features"]
    assert body["account_url"] == "/account"


def test_fake_billing_webhook_requires_valid_signature(commercial_client: TestClient) -> None:
    payload = {
        "event_id": "evt-invalid-signature",
        "telegram_user_id": 702,
        "plan": "pro",
        "subscription_state": "active",
    }

    response = commercial_client.post("/v1/billing/webhooks/fake", json=payload)

    assert response.status_code == 401
    assert response.json()["error_code"] == "BILLING_WEBHOOK_SIGNATURE_INVALID"


def test_fake_billing_webhook_updates_commercial_state_idempotently(commercial_client: TestClient) -> None:
    payload = {
        "event_id": "evt-pro-702",
        "event_type": "subscription.updated",
        "telegram_user_id": 702,
        "plan": "pro",
        "subscription_state": "active",
        "provider_customer_id": "cus_702",
        "provider_subscription_id": "sub_702",
    }
    body = canonical_json_bytes(payload)
    signature = fake_billing_signature(payload, "test-fake-billing-secret")
    headers = {"X-Skillra-Billing-Signature": signature, "Content-Type": "application/json"}

    response = commercial_client.post("/v1/billing/webhooks/fake", content=body, headers=headers)
    duplicate = commercial_client.post("/v1/billing/webhooks/fake", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert response.json()["commercial_state"]["plan"] == "pro"
    assert response.json()["commercial_state"]["locked_features"] == []
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["applied"] is False

    state = commercial_client.get("/v1/users/702/commercial-state")
    assert state.status_code == 200
    assert state.json()["plan"] == "pro"
    assert state.json()["subscription_state"] == "active"


def test_fake_billing_provider_is_disabled_by_default(
    tmp_path: Path,
    service_token: str,
    auth_headers: dict[str, str],
) -> None:
    settings = Settings(
        log_level="CRITICAL",
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'commercial_disabled.db'}",
    )
    app = create_app(settings)
    engine = app.state.db_engine
    payload = {
        "event_id": "evt-disabled",
        "telegram_user_id": 703,
        "plan": "pro",
        "subscription_state": "active",
    }
    body = canonical_json_bytes(payload)
    signature = fake_billing_signature(payload, settings.billing_fake_webhook_secret)

    with TestClient(app) as client:
        client.portal.call(_prepare_database, engine)
        client.headers.update(auth_headers)
        response = client.post(
            "/v1/billing/webhooks/fake",
            content=body,
            headers={"X-Skillra-Billing-Signature": signature, "Content-Type": "application/json"},
        )

    assert response.status_code == 404
    assert response.json()["error_code"] == "BILLING_PROVIDER_NOT_CONFIGURED"


def test_billing_webhook_represents_cancel_refund_payment_failure_states(commercial_client: TestClient) -> None:
    for index, (suffix, subscription_state) in enumerate(
        [
            ("cancel", "cancel_at_period_end"),
            ("expired", "expired"),
            ("refund", "refunded"),
            ("failed", "payment_failed"),
            ("unavailable", "provider_unavailable"),
        ],
        start=1,
    ):
        payload = {
            "event_id": f"evt-{suffix}-704",
            "event_type": "subscription.updated",
            "telegram_user_id": 704 + index,
            "plan": "pro",
            "subscription_state": subscription_state,
            "provider_subscription_id": f"sub_704_{index}",
            "occurred_at": f"2026-05-27T10:0{len(suffix) % 6}:00+00:00",
        }
        body = canonical_json_bytes(payload)
        signature = fake_billing_signature(payload, "test-fake-billing-secret")

        response = commercial_client.post(
            "/v1/billing/webhooks/fake",
            content=body,
            headers={"X-Skillra-Billing-Signature": signature, "Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json()["commercial_state"]["subscription_state"] == subscription_state
        if subscription_state not in {"active", "trialing", "cancel_at_period_end"}:
            assert "career_plan.generate_actions" in response.json()["commercial_state"]["locked_features"]


def test_sandbox_billing_webhook_is_signed_idempotent_and_blocks_out_of_order(
    tmp_path: Path,
    service_token: str,
    auth_headers: dict[str, str],
) -> None:
    settings = Settings(
        log_level="CRITICAL",
        runtime_env="staging",
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'sandbox_billing.db'}",
        billing_sandbox_webhook_enabled=True,
        billing_sandbox_webhook_secret="test-sandbox-secret",
        billing_sandbox_provider_name="manual_invoice",
    )
    app = create_app(settings)
    engine = app.state.db_engine

    with TestClient(app) as client:
        client.portal.call(_prepare_database, engine)
        client.headers.update(auth_headers)
        active_payload = {
            "event_id": "evt-manual-active-705",
            "event_type": "invoice.paid",
            "telegram_user_id": 705,
            "plan": "pro",
            "subscription_state": "active",
            "provider_customer_id": "manual-customer-705",
            "provider_subscription_id": "manual-sub-705",
            "occurred_at": "2026-05-27T12:00:00+00:00",
        }
        active_body = canonical_json_bytes(active_payload)
        active_signature = fake_billing_signature(active_payload, "test-sandbox-secret")

        accepted = client.post(
            "/v1/billing/webhooks/manual_invoice",
            content=active_body,
            headers={"X-Skillra-Billing-Signature": active_signature, "Content-Type": "application/json"},
        )
        replayed = client.post(
            "/v1/billing/webhooks/manual_invoice",
            content=active_body,
            headers={"X-Skillra-Billing-Signature": active_signature, "Content-Type": "application/json"},
        )
        tampered = client.post(
            "/v1/billing/webhooks/manual_invoice",
            content=active_body,
            headers={"X-Skillra-Billing-Signature": "bad-signature", "Content-Type": "application/json"},
        )
        old_payload = {
            **active_payload,
            "event_id": "evt-manual-old-705",
            "subscription_state": "payment_failed",
            "occurred_at": "2026-05-27T11:00:00+00:00",
        }
        old_body = canonical_json_bytes(old_payload)
        old_signature = fake_billing_signature(old_payload, "test-sandbox-secret")
        out_of_order = client.post(
            "/v1/billing/webhooks/manual_invoice",
            content=old_body,
            headers={"X-Skillra-Billing-Signature": old_signature, "Content-Type": "application/json"},
        )
        state = client.get("/v1/users/705/commercial-state")

    assert accepted.status_code == 200
    assert accepted.json()["duplicate"] is False
    assert accepted.json()["applied"] is True
    assert replayed.status_code == 200
    assert replayed.json()["duplicate"] is True
    assert replayed.json()["applied"] is False
    assert tampered.status_code == 401
    assert out_of_order.status_code == 200
    assert out_of_order.json()["duplicate"] is False
    assert out_of_order.json()["applied"] is False
    assert out_of_order.json()["commercial_state"]["subscription_state"] == "active"
    assert state.json()["subscription_state"] == "active"


def test_sandbox_billing_provider_requires_explicit_prod_launch_flag(
    tmp_path: Path,
    service_token: str,
    auth_headers: dict[str, str],
) -> None:
    settings = Settings(
        log_level="CRITICAL",
        runtime_env="prod",
        api_token=service_token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'sandbox_prod_disabled.db'}",
        billing_sandbox_webhook_enabled=True,
        billing_sandbox_webhook_secret="test-sandbox-secret",
        billing_sandbox_provider_name="manual_invoice",
        billing_real_provider_launch_enabled=False,
    )
    app = create_app(settings)
    engine = app.state.db_engine
    payload = {
        "event_id": "evt-prod-blocked",
        "telegram_user_id": 706,
        "plan": "pro",
        "subscription_state": "active",
    }
    body = canonical_json_bytes(payload)
    signature = fake_billing_signature(payload, "test-sandbox-secret")

    with TestClient(app) as client:
        client.portal.call(_prepare_database, engine)
        client.headers.update(auth_headers)
        response = client.post(
            "/v1/billing/webhooks/manual_invoice",
            content=body,
            headers={"X-Skillra-Billing-Signature": signature, "Content-Type": "application/json"},
        )

    assert response.status_code == 404
    assert response.json()["error_code"] == "BILLING_PROVIDER_NOT_CONFIGURED"
