from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select

from skillra_api.config import Settings
from skillra_api.constants import ADMIN_TOKEN_HEADER, SERVICE_TOKEN_HEADER
from skillra_api.deps import get_settings_dependency


def _error_detail(error_code: str, message: str) -> dict[str, object]:
    return {"error_code": error_code, "message": message, "details": {}}


def require_service_token(
    token: str | None = Header(default=None, alias=SERVICE_TOKEN_HEADER),
    settings: Settings = Depends(get_settings_dependency),
) -> str:
    """Validate the service token for protected endpoints."""

    if not settings.api_token:
        raise HTTPException(
            status_code=503,
            detail=_error_detail(
                "SERVICE_TOKEN_NOT_CONFIGURED",
                "Service token is not configured. Set SKILLRA_API_TOKEN.",
            ),
        )

    if not secrets.compare_digest(token or "", settings.api_token):
        raise HTTPException(
            status_code=401,
            detail=_error_detail("INVALID_SERVICE_TOKEN", "Invalid service token."),
        )

    return token


def require_admin_token(
    admin_token: str | None = Header(default=None, alias=ADMIN_TOKEN_HEADER),
    settings: Settings = Depends(get_settings_dependency),
) -> str:
    """Validate the admin token for admin endpoints."""

    if not settings.admin_token:
        raise HTTPException(
            status_code=503,
            detail=_error_detail(
                "ADMIN_TOKEN_NOT_CONFIGURED",
                "Admin token is not configured. Set SKILLRA_ADMIN_TOKEN.",
            ),
        )

    if not secrets.compare_digest(admin_token or "", settings.admin_token):
        raise HTTPException(
            status_code=403,
            detail=_error_detail("ADMIN_TOKEN_REQUIRED", "Admin token is required for admin endpoints."),
        )

    return admin_token


async def require_user_or_service_token(
    request: Request,
    token: str | None = Header(default=None, alias=SERVICE_TOKEN_HEADER),
    authorization: str | None = Header(default=None, alias="Authorization"),
    settings: Settings = Depends(get_settings_dependency),
) -> None:
    """Accept user API key OR static service token.

    Side-effect: sets request.state.telegram_user_id when a valid user key is used.
    Sprint-011 TASK-02 / ADR-008.
    """
    from skillra_api.db.models import User, UserApiKey  # noqa: PLC0415

    auth_token = token
    if not auth_token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            auth_token = value

    if not auth_token:
        raise HTTPException(
            status_code=401,
            detail=_error_detail("AUTHORIZATION_REQUIRED", "X-Skillra-Token header required."),
        )

    # Fast path: service token (no DB)
    if settings.api_token and secrets.compare_digest(auth_token, settings.api_token):
        return

    session_maker = getattr(request.app.state, "session_maker", None)
    if session_maker is None:
        raise HTTPException(
            status_code=401,
            detail=_error_detail("INVALID_USER_API_KEY", "Invalid or revoked user API key."),
        )

    # User API key path — hash lookup
    key_hash = hashlib.sha256(auth_token.encode()).hexdigest()
    async with session_maker() as session:
        api_key = await session.scalar(
            select(UserApiKey).where(UserApiKey.key_hash == key_hash, UserApiKey.revoked_at.is_(None))
        )
        if api_key is None:
            raise HTTPException(
                status_code=401,
                detail=_error_detail("INVALID_USER_API_KEY", "Invalid or revoked user API key."),
            )

        # Inject telegram_user_id into request state
        user_telegram_id = await session.scalar(select(User.telegram_user_id).where(User.id == api_key.user_id))
        request.state.telegram_user_id = user_telegram_id

        # Update last_used_at (best-effort, non-blocking)
        try:
            api_key.last_used_at = datetime.now(tz=timezone.utc)
            await session.commit()
        except Exception:  # noqa: BLE001
            pass


async def require_service_or_matching_user(
    telegram_user_id: int,
    request: Request,
    _: None = Depends(require_user_or_service_token),
) -> None:
    """Allow service token or a user API key that belongs to the requested Telegram user."""

    authenticated_user_id = getattr(request.state, "telegram_user_id", None)
    if authenticated_user_id is None:
        return
    if authenticated_user_id != telegram_user_id:
        raise HTTPException(
            status_code=403,
            detail=_error_detail("USER_SCOPE_FORBIDDEN", "User API key cannot access another Telegram user."),
        )
