import asyncio

import pytest
from skillra_api.config import Settings
from skillra_api.db.session import create_async_engine_from_settings, create_session_maker_from_settings


def test_create_engine_requires_database_url() -> None:
    settings = Settings(database_url=None)

    with pytest.raises(RuntimeError):
        create_async_engine_from_settings(settings)


def test_create_session_maker_from_settings_does_not_connect() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")

    session_maker = create_session_maker_from_settings(settings)

    assert session_maker is not None
    asyncio.run(session_maker.kw["bind"].dispose())
