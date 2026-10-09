"""Centralized SQLAlchemy async database lifecycle management.

The engine and session factory are created on first use.  Importing this module
never opens a connection or creates database objects.  The database URL comes
from the single application configuration object (:class:`app.core.config.Settings`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


DEFAULT_DEVELOPMENT_DATABASE_URL: Final[str] = "sqlite+aiosqlite:///./dev.db"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _environment() -> str:
    return (
        get_settings().environment
        or "development"
    ).strip().lower()


def _is_production() -> bool:
    return _environment() in {"production", "prod"}


def _configured_database_url() -> str:
    """Return the configured database URL, or the development default.

    Production requires an explicit PostgreSQL URL.
    """
    value = get_settings().get_database_url()

    if not value:
        if _is_production():
            raise RuntimeError("DATABASE_URL must be configured in production.")
        value = DEFAULT_DEVELOPMENT_DATABASE_URL

    value = value.strip()
    if not value:
        raise RuntimeError("DATABASE_URL must not be empty.")
    return value


def _normalise_and_validate_url(value: str) -> tuple[str, bool]:
    """Return an async-driver URL and whether it is PostgreSQL.

    Only local SQLite using the async driver is accepted as a development
    database.  PostgreSQL is accepted in every environment, but is mandatory
    in production.
    """
    try:
        parsed = make_url(value)
    except Exception:
        raise RuntimeError("DATABASE_URL is invalid.") from None

    driver = parsed.drivername.lower()
    if driver in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+asyncpg")
        driver = parsed.drivername

    is_postgresql = driver.startswith("postgresql+")
    is_sqlite = driver == "sqlite+aiosqlite"

    if _is_production() and not is_postgresql:
        raise RuntimeError("Production databases must use PostgreSQL.")
    if not is_postgresql and not is_sqlite:
        raise RuntimeError(
            "DATABASE_URL must use PostgreSQL or the safe development SQLite URL."
        )

    return str(parsed), is_postgresql


def get_engine() -> AsyncEngine:
    """Return the lazily-created async engine.

    ``create_async_engine`` only constructs the engine; it does not establish a
    database connection.  Connections are opened by SQLAlchemy when used.
    """
    global _engine

    if _engine is not None:
        return _engine

    configured_url = _configured_database_url()
    database_url, is_postgresql = _normalise_and_validate_url(configured_url)

    options: dict[str, object] = {}
    if is_postgresql:
        options.update(
            pool_pre_ping=True,
            pool_recycle=1800,
        )

    try:
        _engine = create_async_engine(database_url, **options)
    except Exception:
        # Do not expose driver errors because some drivers include the complete
        # URL, including credentials, in their exception text.
        raise RuntimeError("Unable to initialize the database engine.") from None

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-created SQLAlchemy async session factory."""
    global _session_factory

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    """Provide a session with commit, rollback, and close semantics."""
    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-compatible async database dependency."""
    async with session_context() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose all pooled connections and reset the lazy lifecycle."""
    global _engine, _session_factory

    engine = _engine
    _session_factory = None
    _engine = None

    if engine is not None:
        await engine.dispose()


# Common names used by application code and dependency wiring.
get_db = get_session
get_db_session = get_session
session_scope = session_context
close_engine = dispose_engine
