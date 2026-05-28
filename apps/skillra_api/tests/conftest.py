from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

try:  # pragma: no cover - guard for minimal environments without API deps
    import fastapi  # noqa: F401
    import sqlalchemy  # noqa: F401
except ModuleNotFoundError:
    sys.stderr.write("fastapi/SQLAlchemy dependencies are required for API tests; skipping\n")
    raise SystemExit(0)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
APP_SRC = PROJECT_ROOT / "apps" / "skillra_api" / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))


TEST_SERVICE_TOKEN = "test-service-token"
TEST_ADMIN_TOKEN = "test-admin-token"

os.environ["REDIS_URL"] = ""
os.environ["MEILISEARCH_URL"] = ""
os.environ["SENTRY_DSN"] = ""
os.environ["DATABASE_URL"] = ""


@pytest.fixture()
def service_token() -> str:
    return TEST_SERVICE_TOKEN


@pytest.fixture()
def admin_token() -> str:
    return TEST_ADMIN_TOKEN


@pytest.fixture()
def auth_headers(service_token: str) -> dict[str, str]:
    return {"X-Skillra-Token": service_token}


@pytest.fixture()
def admin_headers(auth_headers: dict[str, str], admin_token: str) -> dict[str, str]:
    headers = dict(auth_headers)
    headers["X-Admin-Token"] = admin_token
    return headers


@pytest.fixture(autouse=True)
def ensure_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            yield
        finally:
            asyncio.set_event_loop(None)
            if not loop.is_closed():
                loop.close()
    else:
        yield
