"""SlowAPI key function for per-user API key rate limiting."""

from __future__ import annotations

import hashlib
import secrets

from starlette.requests import Request

from skillra_api.constants import SERVICE_TOKEN_HEADER


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    forwarded_ip = forwarded_for.split(",", 1)[0].strip()
    if forwarded_ip:
        return forwarded_ip
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit_key(request: Request) -> str:
    """Rate limit by user API key material when present, otherwise by client IP."""

    settings = getattr(request.app.state, "settings", None)
    service_token = getattr(settings, "api_token", None)
    token = _bearer_token(request) or request.headers.get(SERVICE_TOKEN_HEADER)

    if token and not (service_token and secrets.compare_digest(token, service_token)):
        digest = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"key:{digest}"

    return f"ip:{_client_ip(request)}"
