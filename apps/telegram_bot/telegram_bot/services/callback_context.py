"""Signed Redis-backed context for Telegram inline callbacks."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

CALLBACK_CONTEXT_VERSION = 1
TOKEN_BYTES = 24


class CallbackContextError(Exception):
    """Raised when a callback context cannot be trusted or resolved."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CallbackContext:
    """Verified callback context loaded from Redis."""

    namespace: str
    token: str
    user_id: int
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: datetime
    expires_at: datetime


class CallbackContextStore:
    """Create and resolve short signed callback IDs with Redis persistence."""

    def __init__(
        self,
        *,
        signing_secret: str,
        redis_url: str | None = None,
        redis_client: Any | None = None,
        key_prefix: str = "bot:callback",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._signing_secret = signing_secret
        self._redis_url = redis_url
        self._redis = redis_client
        self._owns_client = redis_client is None
        self._key_prefix = key_prefix
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def available(self) -> bool:
        return self._redis is not None

    async def connect(self) -> None:
        """Open the Redis client if a URL was provided.

        Bot startup must not fail only because callback durability is down. The
        handlers will fall back to legacy in-process callbacks when unavailable.
        """

        if self._redis is not None or not self._redis_url:
            return

        try:
            from redis import asyncio as redis_asyncio
        except ModuleNotFoundError:
            logger.warning("Redis package unavailable; durable callback context is disabled")
            return

        client = redis_asyncio.from_url(self._redis_url, decode_responses=True)
        try:
            await client.ping()
        except Exception:  # noqa: BLE001
            logger.exception("Redis unavailable; durable callback context is disabled")
            await _close_redis_client(client)
            return

        self._redis = client

    async def close(self) -> None:
        if self._owns_client and self._redis is not None:
            await _close_redis_client(self._redis)
        self._redis = None

    async def create_callback_data(
        self,
        *,
        namespace: str,
        action: str,
        user_id: int,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> str:
        if self._redis is None:
            raise CallbackContextError("redis_unavailable")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")

        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = _ensure_utc(self._now())
        created_at = _format_dt(now)
        expires_at = _format_dt(now + timedelta(seconds=ttl_seconds))
        signature = self._signature(namespace, action, token, user_id, entity_id, expires_at)
        value = {
            "version": CALLBACK_CONTEXT_VERSION,
            "user_id": user_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "payload": payload,
            "created_at": created_at,
            "expires_at": expires_at,
            "signature": signature,
        }
        await self._redis.set(
            self._key(namespace, token),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            ex=ttl_seconds,
        )
        return f"{namespace}:{action}:{token}"

    async def resolve(
        self,
        *,
        namespace: str,
        action: str,
        token: str,
        user_id: int,
    ) -> CallbackContext:
        if self._redis is None:
            raise CallbackContextError("redis_unavailable")

        key = self._key(namespace, token)
        raw = await self._redis.get(key)
        if not raw:
            raise CallbackContextError("missing")

        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CallbackContextError("invalid") from exc
        if not isinstance(value, dict) or value.get("version") != CALLBACK_CONTEXT_VERSION:
            raise CallbackContextError("invalid")

        stored_action = str(value.get("action") or "")
        if stored_action != action:
            raise CallbackContextError("wrong_action")

        stored_user_id = _parse_int(value.get("user_id"))
        if stored_user_id != user_id:
            raise CallbackContextError("wrong_user")

        entity_id = str(value.get("entity_id") or "")
        expires_at_raw = str(value.get("expires_at") or "")
        expires_at = _parse_dt(expires_at_raw)
        if expires_at is None:
            raise CallbackContextError("invalid")
        if _ensure_utc(self._now()) >= expires_at:
            await self._delete_safely(key)
            raise CallbackContextError("expired")

        expected_signature = self._signature(namespace, action, token, user_id, entity_id, expires_at_raw)
        signature = str(value.get("signature") or "")
        if not hmac.compare_digest(signature, expected_signature):
            raise CallbackContextError("invalid")

        created_at = _parse_dt(str(value.get("created_at") or "")) or expires_at
        payload = value.get("payload")
        return CallbackContext(
            namespace=namespace,
            token=token,
            user_id=user_id,
            action=action,
            entity_type=str(value.get("entity_type") or ""),
            entity_id=entity_id,
            payload=payload if isinstance(payload, dict) else {},
            created_at=created_at,
            expires_at=expires_at,
        )

    async def _delete_safely(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to delete expired Telegram callback context", exc_info=True)

    def _key(self, namespace: str, token: str) -> str:
        return f"{self._key_prefix}:{namespace}:{token}"

    def _signature(
        self,
        namespace: str,
        action: str,
        token: str,
        user_id: int,
        entity_id: str,
        expires_at: str,
    ) -> str:
        message = f"{namespace}|{action}|{token}|{user_id}|{entity_id}|{expires_at}"
        return hmac.new(self._signing_secret.encode(), message.encode(), hashlib.sha256).hexdigest()


async def _close_redis_client(client: Any) -> None:
    close = getattr(client, "aclose", None)
    if close is not None:
        await close()
        return

    close = getattr(client, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_dt(value: datetime) -> str:
    return _ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str) -> datetime | None:
    try:
        normalized = value.replace("Z", "+00:00")
        return _ensure_utc(datetime.fromisoformat(normalized))
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
