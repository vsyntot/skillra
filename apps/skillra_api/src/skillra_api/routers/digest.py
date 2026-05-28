from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from skillra_api.datastore import DataStore, DataUnavailableError
from skillra_api.db.models import ApplicationOutcomeEvent, CareerPlan, DigestHistory, ProductEvent, User, UserProfile
from skillra_api.deps import get_datastore_dependency, get_db_session
from skillra_api.deps.auth import require_service_or_matching_user
from skillra_api.schemas import DigestPreviewResponse
from skillra_api.services.analytics import _prepare_persona
from skillra_api.services.digest_builder import (
    DigestActivityContext,
    build_digest_preview,
    build_persona_profile,
    unavailable_digest_response,
)
from skillra_api.services.product_events import build_product_event, normalize_surface
from skillra_api.services.responses import data_unavailable_error, profile_not_found_error
from skillra_pda.personas import Persona, analyze_persona, plot_persona_skill_gap

router = APIRouter(prefix="/v1/users", tags=["digest"])


def _event_source(value: str | None, *, default: str = "digest") -> str:
    return normalize_surface(value, default=default)


def _digest_trust_tier(preview: DigestPreviewResponse) -> str:
    if preview.freshness == "stale":
        return "stale_data"
    if preview.confidence in {"low", "medium"}:
        return "limited_sample"
    if preview.confidence == "high":
        return "trusted"
    return "unknown"


def _add_product_event(
    session: AsyncSession,
    *,
    user_id: int,
    event_type: str,
    source: str,
    entity_type: str,
    payload: dict[str, object] | None,
    occurred_at: datetime,
) -> None:
    session.add(
        build_product_event(
            user_id=user_id,
            event_name=event_type,
            surface=source,
            entity_type=entity_type,
            entity_id=None,
            metadata=payload,
            occurred_at=occurred_at,
        )
    )


def _render_digest_chart(features_df: pd.DataFrame, persona: Persona) -> bytes:
    """Analyse persona and render skill-gap chart to PNG bytes.

    Runs synchronously — must be called via :func:`asyncio.to_thread`
    to avoid blocking the event loop (see ADR-002).
    """

    analysis = analyze_persona(features_df, persona)
    gap_df = analysis.get("skill_gap")
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        image_path = plot_persona_skill_gap(gap_df, persona, output_dir=tmp_path)
        return image_path.read_bytes()


@router.post(
    "/{telegram_user_id}/digest-preview",
    response_model=DigestPreviewResponse,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def digest_preview(
    telegram_user_id: int,
    source: str | None = Query("digest", description="Product event source"),
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> DigestPreviewResponse | JSONResponse:
    result = await session.execute(
        select(User, UserProfile)
        .join(UserProfile, User.id == UserProfile.user_id, isouter=True)
        .where(User.telegram_user_id == telegram_user_id)
    )
    row = result.first()
    if not row or row[1] is None:
        return profile_not_found_error(telegram_user_id)

    user, profile = row
    if not datastore.is_ready:
        return unavailable_digest_response()

    career_plan = await session.scalar(
        select(CareerPlan)
        .options(selectinload(CareerPlan.actions))
        .where(CareerPlan.user_id == user.id)
        .order_by(CareerPlan.id.desc())
    )

    last_sent_at = await session.scalar(
        select(DigestHistory.sent_at)
        .where(DigestHistory.user_id == user.id)
        .order_by(DigestHistory.sent_at.desc())
        .limit(1)
    )
    event_rows = await session.execute(
        select(ProductEvent.event_type, func.count(ProductEvent.id))
        .where(ProductEvent.user_id == user.id)
        .where(ProductEvent.occurred_at > last_sent_at if last_sent_at is not None else ProductEvent.id > 0)
        .group_by(ProductEvent.event_type)
    )
    outcomes = (
        (
            await session.scalars(
                select(ApplicationOutcomeEvent)
                .where(ApplicationOutcomeEvent.user_id == user.id)
                .where(
                    ApplicationOutcomeEvent.occurred_at > last_sent_at
                    if last_sent_at is not None
                    else ApplicationOutcomeEvent.id > 0
                )
                .order_by(ApplicationOutcomeEvent.occurred_at.desc())
                .limit(5)
            )
        )
        .unique()
        .all()
    )
    activity = DigestActivityContext(
        last_sent_at=last_sent_at,
        event_counts=Counter({event_type: int(count) for event_type, count in event_rows.all()}),
        outcome_events=list(outcomes),
    )

    preview = await build_digest_preview(user, profile, datastore, career_plan, activity)
    now = datetime.now(timezone.utc)
    event_source = _event_source(source)
    event_payload = {
        "has_previous_digest": last_sent_at is not None,
        "dataset_run_id": preview.dataset_run_id,
        "confidence": preview.confidence,
        "freshness": preview.freshness,
        "trust_tier": _digest_trust_tier(preview),
    }
    _add_product_event(
        session,
        user_id=user.id,
        event_type="digest_preview_viewed",
        source=event_source,
        entity_type="digest_preview",
        payload=event_payload,
        occurred_at=now,
    )
    _add_product_event(
        session,
        user_id=user.id,
        event_type="digest_engagement",
        source=event_source,
        entity_type="digest_preview",
        payload=event_payload,
        occurred_at=now,
    )
    if last_sent_at is not None:
        _add_product_event(
            session,
            user_id=user.id,
            event_type="weekly_returned",
            source=event_source,
            entity_type="digest_preview",
            payload=event_payload,
            occurred_at=now,
        )
        _add_product_event(
            session,
            user_id=user.id,
            event_type="weekly_return",
            source=event_source,
            entity_type="digest_preview",
            payload=event_payload,
            occurred_at=now,
        )
    await session.commit()
    return preview


@router.get(
    "/{telegram_user_id}/digest-chart",
    response_class=Response,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def digest_chart(
    telegram_user_id: int,
    session: AsyncSession = Depends(get_db_session),
    datastore: DataStore = Depends(get_datastore_dependency),
) -> Response:
    """Render skill-gap chart for the user's saved persona.

    Both :func:`analyze_persona` (pandas) and :func:`plot_persona_skill_gap` (matplotlib)
    run inside a single :func:`asyncio.to_thread` call to avoid blocking the event loop
    (see ADR-002).
    """

    result = await session.execute(
        select(User, UserProfile)
        .join(UserProfile, User.id == UserProfile.user_id, isouter=True)
        .where(User.telegram_user_id == telegram_user_id)
    )
    row = result.first()
    if not row or row[1] is None:
        return profile_not_found_error(telegram_user_id)

    user, profile = row

    if not datastore.is_ready:
        return data_unavailable_error(datastore)

    try:
        features_df = datastore.get_features_df()
    except DataUnavailableError:
        return data_unavailable_error(datastore)

    persona_profile = build_persona_profile(profile, user)
    persona, error_response, _ = _prepare_persona(persona_profile, features_df)
    if error_response:
        return error_response

    assert persona is not None  # noqa: S101 — mypy guard: _prepare_persona guarantees non-None when error_response is None

    try:
        image_bytes = await asyncio.to_thread(_render_digest_chart, features_df, persona)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": "PERSONA_SKILL_GAP_UNAVAILABLE",
                "message": str(exc),
                "details": {},
            },
        )

    return Response(content=image_bytes, media_type="image/png")
