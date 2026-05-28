"""Digest history router (Sprint-007 TASK-07)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from skillra_api.db.models import DigestHistory, User
from skillra_api.deps import get_db_session
from skillra_api.deps.auth import require_service_or_matching_user
from skillra_api.schemas import DigestHistoryItem, DigestHistoryResponse
from skillra_api.services.responses import profile_not_found_error

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/users",
    tags=["digest-history"],
)


@router.get(
    "/{telegram_user_id}/digest/history",
    response_model=DigestHistoryResponse,
    response_class=JSONResponse,
    dependencies=[Depends(require_service_or_matching_user)],
)
async def get_digest_history(
    telegram_user_id: int,
    limit: int = Query(20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    session: AsyncSession = Depends(get_db_session),
) -> DigestHistoryResponse | JSONResponse:
    """Return paginated digest send history for a user."""

    user = await session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        return profile_not_found_error(telegram_user_id)

    total = await session.scalar(select(func.count(DigestHistory.id)).where(DigestHistory.user_id == user.id)) or 0

    result = await session.execute(
        select(DigestHistory)
        .where(DigestHistory.user_id == user.id)
        .order_by(DigestHistory.sent_at.desc())
        .limit(limit)
        .offset(offset)
    )
    records = result.scalars().all()

    items = [
        DigestHistoryItem(
            id=r.id,
            sent_at=r.sent_at,
            format=r.format,
            text_preview=r.text_preview,
            attempt=r.attempt,
        )
        for r in records
    ]

    return DigestHistoryResponse(items=items, total=total)
