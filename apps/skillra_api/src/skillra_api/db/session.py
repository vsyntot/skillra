"""Database session and engine helpers for Skillra API."""

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from skillra_api.config import Settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for ORM models with consistent naming convention."""

    metadata = metadata_obj


def _get_database_url(settings: Settings) -> str:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return settings.database_url


def create_async_engine_from_settings(settings: Settings, *, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine from provided settings."""

    database_url = _get_database_url(settings)
    return create_async_engine(database_url, echo=echo, future=True)


def create_session_maker(engine: AsyncEngine, *, expire_on_commit: bool = False) -> async_sessionmaker[AsyncSession]:
    """Return a configured async session maker for the given engine."""

    return async_sessionmaker(engine, expire_on_commit=expire_on_commit, class_=AsyncSession)


def create_session_maker_from_settings(
    settings: Settings, *, echo: bool = False, expire_on_commit: bool = False
) -> async_sessionmaker[AsyncSession]:
    """Convenience helper to construct engine and session maker from settings."""

    engine = create_async_engine_from_settings(settings, echo=echo)
    return create_session_maker(engine, expire_on_commit=expire_on_commit)
