"""Product event validation, redaction and persistence helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from skillra_api.db.models import ProductEvent
from skillra_api.metrics import PRODUCT_EVENTS_TOTAL
from sqlalchemy.ext.asyncio import AsyncSession

PRODUCT_EVENT_NAMES = {
    "user_started",
    "login_succeeded",
    "profile_started",
    "profile_completed",
    "profile_updated",
    "resume_uploaded",
    "profile_quality_viewed",
    "first_session_viewed",
    "first_session_step_viewed",
    "first_session_step_clicked",
    "market_fit_viewed",
    "market_trust_warning_shown",
    "skill_gap_viewed",
    "skill_gap_action_generated",
    "trend_viewed",
    "share_link_created",
    "report_exported",
    "plan_viewed",
    "plan_created",
    "plan_updated",
    "next_action_viewed",
    "next_action_accepted",
    "plan_action_status_updated",
    "plan_review_completed",
    "action_created",
    "action_completed",
    "plan_actions_generated",
    "vacancy_search_performed",
    "vacancy_evidence_viewed",
    "vacancy_match_explained",
    "vacancy_saved",
    "application_outcome",
    "application_outcome_updated",
    "search_degraded_warning_shown",
    "digest_subscribed",
    "digest_preview_viewed",
    "digest_sent",
    "digest_opened",
    "digest_action_clicked",
    "digest_engagement",
    "weekly_return",
    "weekly_returned",
    "subscription_paused",
    "subscription_resumed",
    "subscription_unsubscribed",
    "api_key_created",
    "api_key_revoked",
    "privacy_viewed",
    "delete_requested",
    "delete_completed",
    "organization_member_updated",
    "organization_owner_transferred",
    "cohort_member_updated",
    "first_value_reached",
}

PRODUCT_EVENT_SURFACES = {"api", "web", "bot", "worker", "digest", "admin", "user", "system"}
USER_ACTIVATION_EVENT_SURFACES = {"web", "bot", "digest", "user"}
PRODUCT_EVENT_METRIC_NAMES = PRODUCT_EVENT_NAMES | {"other"}
PRODUCT_EVENT_METRIC_SURFACES = PRODUCT_EVENT_SURFACES | {"other"}

FORBIDDEN_METADATA_KEYS = {
    "api_key",
    "authorization",
    "billing_email",
    "customer_email",
    "email",
    "message",
    "message_text",
    "name",
    "note",
    "password",
    "phone",
    "presigned_url",
    "provider_payload",
    "query",
    "raw_payload",
    "raw_query",
    "raw_resume",
    "raw_text",
    "resume_text",
    "s3_key",
    "secret",
    "signature",
    "telegram_user_id",
    "text",
    "token",
    "username",
    "webhook_payload",
}
FORBIDDEN_METADATA_KEY_SUFFIXES = (
    "_api_key",
    "_email",
    "_password",
    "_phone",
    "_s3_key",
    "_secret",
    "_signature",
    "_telegram_user_id",
    "_token",
    "_url",
)
MAX_METADATA_STRING_LENGTH = 256
MAX_METADATA_LIST_ITEMS = 25
MAX_CONTEXT_STRING_LENGTH = 128
CAMEL_CASE_ACRONYM = re.compile(r"(.)([A-Z][a-z]+)")
CAMEL_CASE_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


class ProductEventValidationError(ValueError):
    """Raised when a product event violates the canonical analytics contract."""


def bounded_metric_label(value: str | None, allowed: set[str], default: str = "other") -> str:
    if not value:
        return default
    normalized = str(value).strip().lower()
    return normalized if normalized in allowed else default


def normalize_event_name(event_name: str) -> str:
    normalized = str(event_name or "").strip().lower()
    if normalized not in PRODUCT_EVENT_NAMES:
        raise ProductEventValidationError(f"Unsupported product event: {event_name}")
    return normalized


def normalize_surface(surface: str | None, *, default: str = "api") -> str:
    return bounded_metric_label(surface, PRODUCT_EVENT_SURFACES, default=default)


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {str(key): _sanitize_value(str(key), value) for key, value in metadata.items() if value is not None}


def _normalized_metadata_key(key: str) -> str:
    normalized = CAMEL_CASE_ACRONYM.sub(r"\1_\2", key.strip())
    normalized = CAMEL_CASE_BOUNDARY.sub(r"\1_\2", normalized).replace("-", "_").replace(".", "_").lower()
    return re.sub(r"_+", "_", normalized).strip("_")


def _is_forbidden_metadata_key(key: str) -> bool:
    normalized = _normalized_metadata_key(key)
    return normalized in FORBIDDEN_METADATA_KEYS or normalized.endswith(FORBIDDEN_METADATA_KEY_SUFFIXES)


def _sanitize_value(key: str, value: Any) -> Any:
    if _is_forbidden_metadata_key(key):
        return "[redacted]"
    if isinstance(value, dict):
        return sanitize_metadata(value)
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value[:MAX_METADATA_LIST_ITEMS]]
    if isinstance(value, tuple):
        return [_sanitize_value(key, item) for item in value[:MAX_METADATA_LIST_ITEMS]]
    if isinstance(value, str):
        return value[:MAX_METADATA_STRING_LENGTH]
    if isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_METADATA_STRING_LENGTH]


def _normalize_context_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:MAX_CONTEXT_STRING_LENGTH] if normalized else None


def build_product_event(
    *,
    user_id: int,
    event_name: str,
    surface: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> ProductEvent:
    normalized_name = normalize_event_name(event_name)
    normalized_surface = normalize_surface(surface)
    PRODUCT_EVENTS_TOTAL.labels(
        event_type=bounded_metric_label(normalized_name, PRODUCT_EVENT_METRIC_NAMES),
        source=bounded_metric_label(normalized_surface, PRODUCT_EVENT_METRIC_SURFACES),
    ).inc()
    return ProductEvent(
        user_id=user_id,
        event_type=normalized_name,
        source=normalized_surface,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=_normalize_context_value(request_id),
        session_id=_normalize_context_value(session_id),
        correlation_id=_normalize_context_value(correlation_id),
        payload=sanitize_metadata(metadata),
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )


async def record_product_event(
    session: AsyncSession,
    *,
    user_id: int,
    event_name: str,
    surface: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> ProductEvent:
    event = build_product_event(
        user_id=user_id,
        event_name=event_name,
        surface=surface,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id,
        session_id=session_id,
        correlation_id=correlation_id,
        metadata=metadata,
        occurred_at=occurred_at,
    )
    session.add(event)
    await session.flush()
    return event
