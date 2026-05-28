from __future__ import annotations

from types import SimpleNamespace

from skillra_api.config import Settings
from skillra_api.constants import SERVICE_TOKEN_HEADER
from skillra_api.middlewares.rate_limit_key import rate_limit_key
from starlette.requests import Request


def _request(headers: dict[str, str], *, host: str = "10.0.0.1") -> Request:
    settings = Settings(log_level="CRITICAL", api_token="service-token", database_url="", meilisearch_url="")
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": (host, 12345),
        "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
    }
    return Request(scope)


def test_rate_limit_per_user_key_independent_of_ip() -> None:
    first = rate_limit_key(_request({"Authorization": "Bearer sk_user_one"}, host="203.0.113.10"))
    second = rate_limit_key(_request({"Authorization": "Bearer sk_user_two"}, host="203.0.113.10"))

    assert first.startswith("key:")
    assert second.startswith("key:")
    assert first != second


def test_rate_limit_fallback_to_ip_without_key() -> None:
    first = rate_limit_key(_request({"X-Forwarded-For": "198.51.100.7, 10.0.0.2"}))
    second = rate_limit_key(_request({SERVICE_TOKEN_HEADER: "service-token", "X-Forwarded-For": "198.51.100.7"}))

    assert first == "ip:198.51.100.7"
    assert second == "ip:198.51.100.7"
