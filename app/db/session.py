"""Centralized SQLAlchemy async database lifecycle management.

The engine and session factory are created on first use.  Importing this module
never opens a connection or creates database objects.  The database URL comes
from the single application configuration object (:class:`app.core.config.Settings`).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


DEFAULT_DEVELOPMENT_DATABASE_URL: Final[str] = "sqlite+aiosqlite:///./dev.db"

# ``asyncpg`` does not accept libpq-only query parameters as keyword arguments,
# yet the SQLAlchemy asyncpg dialect forwards every URL query parameter
# verbatim. Neon connection strings ship ``?sslmode=require`` (and often
# ``channel_binding=require``), so they are translated before the engine is
# created.
_SSL_MODE_PARAM: Final[str] = "sslmode"
_ASYNC_UNSUPPORTED_LIBPQ_PARAMS: Final[tuple[str, ...]] = ("channel_binding",)

# Kept as a public setting for applications and tests that configure the module
# directly.  The environment is checked again when the engine is first used so
# late environment configuration still works.
DATABASE_URL: str | None = os.getenv("DATABASE_URL")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _environment() -> str:
    return (
        get_settings().environment
        or "development"
    ).strip().lower()


_PRODUCTION_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"production", "prod"})

# Deliberately free of the URL, driver, host, user, or password: this message
# can reach logs and CI output.
_PRODUCTION_DATABASE_URL_ERROR: Final[str] = (
    "DATABASE_URL must be configured with a PostgreSQL URL in production."
)


def is_production_environment(environment: str | None) -> bool:
    """Return whether ``environment`` names a production environment."""
    return (environment or "").strip().lower() in _PRODUCTION_ENVIRONMENTS


def validate_migration_database_url(value: str, environment: str | None) -> str:
    """Validate a database URL before Alembic runs any migration.

    Outside production the value is returned unchanged. In production the URL
    must point at PostgreSQL (``postgres`` or ``postgresql`` with an optional
    driver suffix); anything else raises a fixed :class:`RuntimeError` that
    never includes the original value, so credentials cannot leak.
    """
    if not is_production_environment(environment):
        return value

    try:
        driver = make_url(value).drivername.strip().lower()
    except Exception:
        raise RuntimeError(_PRODUCTION_DATABASE_URL_ERROR) from None

    if driver == "postgres" or driver.startswith("postgresql"):
        return value

    raise RuntimeError(_PRODUCTION_DATABASE_URL_ERROR) from None


def _is_production() -> bool:
    return is_production_environment(_environment())


def _configured_database_url() -> str:
    """Return the configured database URL, or the development default.

    Resolution order: the ``DATABASE_URL`` environment variable, then the
    module-level :data:`DATABASE_URL` (kept for compatibility with existing
    wiring and tests), then application settings.  Production requires an
    explicit PostgreSQL URL.
    """
    value = os.getenv("DATABASE_URL") or DATABASE_URL or get_settings().get_database_url()

    if not value:
        if _is_production():
            raise RuntimeError("DATABASE_URL must be configured in production.")
        value = DEFAULT_DEVELOPMENT_DATABASE_URL

    value = value.strip()
    if not value:
        raise RuntimeError("DATABASE_URL must not be empty.")
    return value


def _parse_url(value: str) -> URL:
    try:
        return make_url(value)
    except Exception:
        raise RuntimeError("DATABASE_URL is invalid.") from None


def _split_asyncpg_params(parsed: URL) -> tuple[URL, dict[str, object]]:
    """Translate libpq query parameters into asyncpg connect arguments.

    Returns the URL without the translated parameters plus the ``connect_args``
    asyncpg needs. ``sslmode`` becomes the asyncpg ``ssl`` argument (which
    accepts the libpq mode string, for example ``require``); parameters asyncpg
    cannot accept as keyword arguments are removed.
    """
    query = dict(parsed.query)
    if not query:
        return parsed, {}

    connect_args: dict[str, object] = {}
    sslmode = query.pop(_SSL_MODE_PARAM, None)
    if sslmode:
        connect_args["ssl"] = sslmode
    for name in _ASYNC_UNSUPPORTED_LIBPQ_PARAMS:
        query.pop(name, None)

    if query == dict(parsed.query):
        return parsed, connect_args
    return parsed.set(query=query), connect_args


def _to_asyncpg_url(parsed: URL) -> tuple[URL, dict[str, object]]:
    """Point a PostgreSQL URL at the asyncpg driver and translate libpq params."""
    driver = parsed.drivername.lower()
    if driver in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+asyncpg")
        driver = parsed.drivername
    if driver == "postgresql+asyncpg":
        return _split_asyncpg_params(parsed)
    return parsed, {}


def prepare_async_url(value: str) -> tuple[str, dict[str, object]]:
    """Return ``(async_url, connect_args)`` for the async engine and Alembic.

    Normalises a bare ``postgres``/``postgresql`` URL to the ``asyncpg`` driver
    and translates libpq-only query parameters (``sslmode``) into asyncpg
    connect arguments. Non-PostgreSQL URLs are returned unchanged with no extra
    connect arguments.

    The returned string is meant only for the engine and the migration tool; it
    is never logged, and the password must stay intact so authentication works
    (``str(URL)`` would mask it).
    """
    parsed, connect_args = _to_asyncpg_url(_parse_url(value))
    return parsed.render_as_string(hide_password=False), connect_args


def _normalise_and_validate_url(value: str) -> tuple[str, bool]:
    """Return an async-driver URL and whether it is PostgreSQL.

    Only local SQLite using the async driver is accepted as a development
    database.  PostgreSQL is accepted in every environment, but is mandatory
    in production.
    """
    parsed = _to_asyncpg_url(_parse_url(value))[0]

    driver = parsed.drivername.lower()
    is_postgresql = driver.startswith("postgresql+")
    is_sqlite = driver == "sqlite+aiosqlite"

    if _is_production() and not is_postgresql:
        raise RuntimeError("Production databases must use PostgreSQL.")
    if not is_postgresql and not is_sqlite:
        raise RuntimeError(
            "DATABASE_URL must use PostgreSQL or the safe development SQLite URL."
        )

    # ``str(URL)`` masks the password; the engine needs the real value.
    return parsed.render_as_string(hide_password=False), is_postgresql


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
        _, connect_args = prepare_async_url(configured_url)
        if connect_args:
            options["connect_args"] = connect_args

    try:
        # ``echo`` stays disabled: SQLAlchemy would otherwise log bound
        # parameters, which can contain analyzed user code. The logging filter
        # in ``app.core.logging`` is the defense in depth for exceptions.
        _engine = create_async_engine(database_url, echo=False, **options)
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
