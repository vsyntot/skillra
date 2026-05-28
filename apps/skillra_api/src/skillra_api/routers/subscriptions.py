from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from skillra_api.config import get_settings
from skillra_api.db.models import DigestHistory, User, WeeklySubscription
from skillra_api.deps import get_db_session
from skillra_api.deps.auth import require_service_or_matching_user, require_service_token
from skillra_api.metrics import DIGESTS_SENT_TOTAL
from skillra_api.services.product_events import build_product_event, normalize_surface

logger = logging.getLogger(__name__)
from skillra_api.schemas import (
    AckSubscriptionRequest,
    ClaimedSubscription,
    ClaimSubscriptionsRequest,
    ClaimSubscriptionsResponse,
    DueSubscription,
    DueSubscriptionsResponse,
    MarkSentRequest,
    WeeklySubscriptionIn,
    WeeklySubscriptionOut,
)
from skillra_api.services.responses import (
    invalid_time_error,
    invalid_timestamp_error,
    invalid_timezone_error,
    subscription_lock_mismatch_error,
    subscription_not_claimed_error,
    subscription_not_found_error,
)

router = APIRouter(prefix="/v1", tags=["subscriptions"])


def _subscription_out(user: User, subscription: WeeklySubscription) -> WeeklySubscriptionOut:
    return WeeklySubscriptionOut(
        telegram_user_id=user.telegram_user_id,
        active=subscription.active,
        weekday=subscription.weekday,
        time_local=subscription.time_local,
        timezone=subscription.timezone,
        last_sent_at=subscription.last_sent_at,
    )


def _parse_time_local(time_local: str) -> Tuple[int, int] | None:
    if len(time_local) != 5 or time_local[2] != ":":
        return None
    try:
        hours = int(time_local[:2])
        minutes = int(time_local[3:])
    except ValueError:
        return None
    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return None
    return hours, minutes


def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # SQLite может вернуть naive datetime даже при DateTime(timezone=True); считаем это UTC.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _zoneinfo_or_error(timezone_name: str) -> ZoneInfo | JSONResponse:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return invalid_timezone_error(timezone_name)


def _is_subscription_due(subscription: WeeklySubscription, parsed_now: datetime) -> tuple[bool, JSONResponse | None]:
    tzinfo = _zoneinfo_or_error(subscription.timezone)
    if isinstance(tzinfo, JSONResponse):
        return False, tzinfo

    local_now = parsed_now.astimezone(tzinfo)
    if local_now.weekday() != subscription.weekday:
        return False, None

    local_hhmm = local_now.strftime("%H:%M")
    if local_hhmm < subscription.time_local:
        return False, None

    if subscription.last_sent_at is not None:
        last_sent_at = _ensure_aware_utc(subscription.last_sent_at)
        last_sent_local = last_sent_at.astimezone(tzinfo)
        if last_sent_local.date() == local_now.date():
            return False, None

    return True, None


def _parse_now_utc(now_utc: datetime | str | None) -> tuple[datetime | None, JSONResponse | None]:
    if now_utc is None:
        return datetime.now(timezone.utc), None

    if isinstance(now_utc, datetime):
        if now_utc.tzinfo is None:
            return None, invalid_timestamp_error(now_utc.isoformat())
        return now_utc.astimezone(timezone.utc), None

    try:
        parsed = datetime.fromisoformat(now_utc)
    except ValueError:
        return None, invalid_timestamp_error(now_utc)
    if parsed.tzinfo is None:
        return None, invalid_timestamp_error(now_utc)
    return parsed.astimezone(timezone.utc), None


def _candidate_weekdays(utc_now: datetime) -> set[int]:
    """Return weekday candidates covering all UTC offsets (UTC-12 … UTC+14).

    Because a subscription stores local time with an IANA timezone, filtering
    purely by UTC weekday would miss users whose local day differs from UTC.
    We include the previous, current, and next UTC weekday so that exact
    timezone-based filtering in Python never misses due to day boundaries.
    """
    wd = utc_now.weekday()
    return {(wd - 1) % 7, wd, (wd + 1) % 7}


@router.put(
    "/users/{telegram_user_id}/subscriptions/weekly",
    response_model=WeeklySubscriptionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def upsert_weekly_subscription(
    telegram_user_id: int,
    payload: WeeklySubscriptionIn,
    session: AsyncSession = Depends(get_db_session),
) -> WeeklySubscriptionOut | JSONResponse:
    hours_minutes = _parse_time_local(payload.time_local)
    if hours_minutes is None:
        return invalid_time_error(payload.time_local)

    tzinfo = _zoneinfo_or_error(payload.timezone)
    if isinstance(tzinfo, JSONResponse):
        return tzinfo

    weekday = payload.weekday % 7

    async with session.begin():
        user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
        if not user:
            user = User(telegram_user_id=telegram_user_id)
            session.add(user)
            await session.flush()

        subscription = await session.scalar(select(WeeklySubscription).where(WeeklySubscription.user_id == user.id))

        was_active = bool(subscription.active) if subscription else False
        event_type = "digest_subscribed"
        if not subscription:
            subscription = WeeklySubscription(
                user_id=user.id,
                active=payload.active if payload.active is not None else True,
                weekday=weekday,
                time_local=payload.time_local,
                timezone=payload.timezone,
            )
            session.add(subscription)
            event_type = "digest_subscribed" if subscription.active else "subscription_paused"
        else:
            subscription.active = payload.active if payload.active is not None else True
            subscription.weekday = weekday
            subscription.time_local = payload.time_local
            subscription.timezone = payload.timezone
            if subscription.active and not was_active:
                event_type = "subscription_resumed"
            elif not subscription.active:
                event_type = "subscription_paused"
            else:
                event_type = "digest_subscribed"
        session.add(
            build_product_event(
                user_id=user.id,
                event_name=event_type,
                surface=normalize_surface(payload.source),
                entity_type="weekly_subscription",
                metadata={"active": bool(subscription.active), "weekday": weekday, "timezone": payload.timezone},
            )
        )

    await session.refresh(user)
    await session.refresh(subscription)

    return _subscription_out(user, subscription)


@router.get(
    "/users/{telegram_user_id}/subscriptions/weekly",
    response_model=WeeklySubscriptionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_weekly_subscription(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> WeeklySubscriptionOut | JSONResponse:
    result = await session.execute(
        select(User, WeeklySubscription)
        .join(WeeklySubscription, WeeklySubscription.user_id == User.id)
        .where(User.telegram_user_id == telegram_user_id)
    )
    row = result.first()
    if not row:
        return subscription_not_found_error(telegram_user_id)

    user, subscription = row
    return _subscription_out(user, subscription)


@router.delete(
    "/users/{telegram_user_id}/subscriptions/weekly",
    response_model=None,
    response_class=Response,
    status_code=204,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def delete_weekly_subscription(
    telegram_user_id: int,
    source: str | None = Query(None, max_length=32),
    session: AsyncSession = Depends(get_db_session),
) -> Response | JSONResponse:
    result = await session.execute(
        select(WeeklySubscription)
        .join(User, WeeklySubscription.user_id == User.id)
        .where(User.telegram_user_id == telegram_user_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        return subscription_not_found_error(telegram_user_id)

    session.add(
        build_product_event(
            user_id=subscription.user_id,
            event_name="subscription_unsubscribed",
            surface=normalize_surface(source),
            entity_type="weekly_subscription",
        )
    )
    await session.delete(subscription)
    await session.commit()

    return Response(status_code=204)


@router.get(
    "/subscriptions/due",
    response_model=DueSubscriptionsResponse,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def list_due_subscriptions(
    now_utc: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> DueSubscriptionsResponse | JSONResponse:
    parsed_now, error = _parse_now_utc(now_utc)
    if error:
        return error
    if parsed_now is None:  # defensive guard — _parse_now_utc guarantees non-None when error is None
        return invalid_timestamp_error(str(now_utc))

    result = await session.execute(
        select(WeeklySubscription, User.telegram_user_id)
        .join(User, WeeklySubscription.user_id == User.id)
        .where(
            WeeklySubscription.active.is_(True),
            WeeklySubscription.weekday.in_(_candidate_weekdays(parsed_now)),
        )
    )

    due_subscriptions = []
    for subscription, telegram_user_id in result.all():
        is_due, tz_error = _is_subscription_due(subscription, parsed_now)
        if tz_error:
            return tz_error
        if not is_due:
            continue

        due_subscriptions.append(
            DueSubscription(
                telegram_user_id=telegram_user_id,
                weekday=subscription.weekday,
                time_local=subscription.time_local,
                timezone=subscription.timezone,
                last_sent_at=subscription.last_sent_at,
            )
        )

    return DueSubscriptionsResponse(subscriptions=due_subscriptions)


@router.post(
    "/subscriptions/weekly/claim",
    response_model=ClaimSubscriptionsResponse,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def claim_due_subscriptions(
    payload: ClaimSubscriptionsRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> ClaimSubscriptionsResponse | JSONResponse:
    payload = payload or ClaimSubscriptionsRequest()

    parsed_now, error = _parse_now_utc(payload.now_utc)
    if error:
        return error
    if parsed_now is None:  # defensive guard
        return invalid_timestamp_error(str(payload.now_utc))

    lock_threshold = parsed_now - timedelta(seconds=payload.stale_lock_seconds)

    result = await session.execute(
        select(WeeklySubscription, User.telegram_user_id)
        .join(User, WeeklySubscription.user_id == User.id)
        .where(
            WeeklySubscription.active.is_(True),
            WeeklySubscription.weekday.in_(_candidate_weekdays(parsed_now)),
        )
    )

    claimed: list[ClaimedSubscription] = []

    settings = get_settings()

    for subscription, telegram_user_id in result.all():
        is_due, tz_error = _is_subscription_due(subscription, parsed_now)
        if tz_error:
            return tz_error
        if not is_due:
            continue

        # Sprint-006 TASK-04: Skip if max_attempt reached
        if (subscription.attempt or 0) >= settings.subscription_max_attempt:
            logger.warning(
                "subscription_max_attempt_reached telegram_user_id=%d attempt=%d",
                telegram_user_id,
                subscription.attempt,
            )
            continue

        # Sprint-006 TASK-04: Skip if in backoff period
        if subscription.backoff_until:
            backoff_until = _ensure_aware_utc(subscription.backoff_until)
            if backoff_until and backoff_until > parsed_now:
                continue

        updated_at = _ensure_aware_utc(subscription.updated_at)
        if subscription.lock and updated_at and updated_at > lock_threshold:
            continue

        subscription.lock = uuid4().hex
        subscription.attempt = (subscription.attempt or 0) + 1

        claimed.append(
            ClaimedSubscription(
                telegram_user_id=telegram_user_id,
                weekday=subscription.weekday,
                time_local=subscription.time_local,
                timezone=subscription.timezone,
                lock=subscription.lock,
                attempt=subscription.attempt,
                last_sent_at=subscription.last_sent_at,
            )
        )

    await session.commit()

    return ClaimSubscriptionsResponse(subscriptions=claimed)


@router.post(
    "/subscriptions/weekly/ack-sent",
    response_model=WeeklySubscriptionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def ack_subscription_sent(
    payload: AckSubscriptionRequest,
    session: AsyncSession = Depends(get_db_session),
) -> WeeklySubscriptionOut | JSONResponse:
    parsed_now, error = _parse_now_utc(payload.now_utc)
    if error:
        return error
    if parsed_now is None:  # defensive guard — _parse_now_utc guarantees non-None when error is None
        return invalid_timestamp_error(str(payload.now_utc))

    result = await session.execute(
        select(WeeklySubscription, User)
        .join(User, WeeklySubscription.user_id == User.id)
        .where(User.telegram_user_id == payload.telegram_user_id)
    )
    row = result.first()
    if not row:
        return subscription_not_found_error(payload.telegram_user_id)

    subscription, user = row
    if subscription.lock is None:
        return subscription_not_claimed_error(payload.telegram_user_id)
    if subscription.lock != payload.lock:
        return subscription_lock_mismatch_error(payload.telegram_user_id)

    subscription.last_sent_at = parsed_now
    subscription.lock = None
    subscription.attempt = 0
    subscription.backoff_until = None  # Sprint-006 TASK-04: reset backoff on success

    # Sprint-007 TASK-07: Record successful delivery in DigestHistory
    history = DigestHistory(
        user_id=subscription.user_id,
        sent_at=parsed_now,
        format="HTML",
        attempt=subscription.attempt or 1,
        text_preview=payload.text_preview,
    )
    session.add(history)

    await session.commit()
    DIGESTS_SENT_TOTAL.inc()

    await session.refresh(subscription)
    return _subscription_out(user, subscription)


@router.post(
    "/subscriptions/weekly/ack-failed",
    response_model=WeeklySubscriptionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def ack_subscription_failed(
    payload: AckSubscriptionRequest,
    session: AsyncSession = Depends(get_db_session),
) -> WeeklySubscriptionOut | JSONResponse:
    _parsed_now, error = _parse_now_utc(payload.now_utc)
    if error:
        return error

    result = await session.execute(
        select(WeeklySubscription, User)
        .join(User, WeeklySubscription.user_id == User.id)
        .where(User.telegram_user_id == payload.telegram_user_id)
    )
    row = result.first()
    if not row:
        return subscription_not_found_error(payload.telegram_user_id)

    subscription, user = row
    if subscription.lock is None:
        return subscription_not_claimed_error(payload.telegram_user_id)
    if subscription.lock != payload.lock:
        return subscription_lock_mismatch_error(payload.telegram_user_id)

    # Release lock but keep attempt counter — it accumulates since the last successful send.
    # Semantics: attempt counts total delivery attempts since last ack-sent (reset to 0).
    # High attempt values indicate persistent delivery problems and should be investigated.
    current_attempt = subscription.attempt or 0
    if current_attempt >= 3:
        logger.warning(
            "subscription_high_attempt_count telegram_user_id=%d attempt=%d",
            payload.telegram_user_id,
            current_attempt,
        )
        # Sprint-006 TASK-04: Set backoff_until to delay next retry
        settings = get_settings()
        backoff_dt = _parsed_now + timedelta(seconds=settings.subscription_backoff_seconds) if _parsed_now else None
        subscription.backoff_until = backoff_dt
    subscription.lock = None
    await session.commit()

    await session.refresh(subscription)
    return _subscription_out(user, subscription)


@router.post(
    "/users/{telegram_user_id}/subscriptions/weekly/mark-sent",
    response_model=WeeklySubscriptionOut,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_token)],
)
async def mark_subscription_sent(
    telegram_user_id: int,
    payload: MarkSentRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> WeeklySubscriptionOut | JSONResponse:
    payload = payload or MarkSentRequest()

    mark_time = payload.now_utc
    if mark_time is None:
        mark_time = datetime.now(timezone.utc)
    elif mark_time.tzinfo is None:
        return invalid_timestamp_error(None)
    else:
        mark_time = mark_time.astimezone(timezone.utc)

    result = await session.execute(
        select(WeeklySubscription, User)
        .join(User, WeeklySubscription.user_id == User.id)
        .where(User.telegram_user_id == telegram_user_id)
    )
    row = result.first()
    if not row:
        return subscription_not_found_error(telegram_user_id)

    subscription, user = row

    subscription.last_sent_at = mark_time
    await session.commit()

    await session.refresh(subscription)
    return _subscription_out(user, subscription)


@router.get("/subscriptions/active", response_class=JSONResponse, dependencies=[Depends(require_service_token)])
async def list_active_subscribers(
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Return list of active weekly subscribers (telegram_user_id only).
    Used by the Telegram bot to broadcast market-data-updated notifications.
    Sprint-009 TASK-07.
    """
    result = await session.execute(
        select(User.telegram_user_id)
        .join(WeeklySubscription, WeeklySubscription.user_id == User.id)
        .where(WeeklySubscription.active.is_(True))
    )
    user_ids = [{"telegram_user_id": row[0]} for row in result.all()]
    return JSONResponse(content=user_ids)
