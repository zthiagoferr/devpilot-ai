"""Alembic environment configuration.

The persistence metadata is imported without importing the application entrypoint
or creating a database engine. Engines are created only when online migrations
run.
"""

from __future__ import annotations

import asyncio
import importlib
import os
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config


config = context.config

# Modules that may expose the declarative metadata, newest layout first.  The
# application keeps its ORM models in ``app.db.models``; the ``app.persistence.*``
# names are retained as a fallback for older layouts.
_METADATA_MODULES = (
    "app.db.models",
    "app.persistence.database",
    "app.persistence.base",
    "app.persistence.models",
)

# Safe development default, kept in sync with app.db.session.
_DEFAULT_DEVELOPMENT_DATABASE_URL = "sqlite+aiosqlite:///./dev.db"


def _load_metadata() -> Any:
    """Load the ORM metadata without initializing a database connection."""
    for module_name in _METADATA_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            continue

        base = getattr(module, "Base", None)
        if base is not None and hasattr(base, "metadata"):
            return base.metadata

        metadata = getattr(module, "metadata", None)
        if metadata is None:
            metadata = getattr(module, "target_metadata", None)
        if metadata is not None:
            return metadata

    raise ImportError(
        "Could not locate ORM metadata. Expected a Base.metadata attribute in "
        "app.db.models."
    )


def _settings_database_url() -> str | None:
    """Return the database URL from application settings, if configured."""
    from app.core.config import get_settings

    settings = get_settings()
    accessor = getattr(settings, "get_database_url", None)
    if accessor is None:
        return None

    value = accessor()
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _get_database_url() -> str:
    """Return the unredacted database URL used by Alembic.

    Resolution order matches the application: explicit settings first, then the
    ``DATABASE_URL`` environment variable, then the safe development default
    used by :mod:`app.db.session`.
    """
    try:
        value = _settings_database_url()
    except ImportError:
        value = None
    if value:
        return value

    value = os.getenv("DATABASE_URL")
    if value and value.strip():
        return value.strip()

    try:
        from app.db.session import DEFAULT_DEVELOPMENT_DATABASE_URL

        return DEFAULT_DEVELOPMENT_DATABASE_URL
    except ImportError:
        return _DEFAULT_DEVELOPMENT_DATABASE_URL


def _prepare_database_url(value: str) -> tuple[str, dict[str, object]]:
    """Normalise the URL with the same helper the application uses.

    This keeps Alembic's driver selection and libpq parameter handling
    (``sslmode`` for Neon) aligned with :mod:`app.db.session`.
    """
    try:
        from app.db.session import prepare_async_url
    except ImportError:
        return value, {}
    return prepare_async_url(value)


def _configure_database_url() -> tuple[str, dict[str, object]]:
    """Put the settings URL into Alembic's configuration.

    Returns the normalised URL together with the asyncpg connect arguments that
    migrations must apply (for example the translated ``ssl`` argument).
    """
    url, connect_args = _prepare_database_url(_get_database_url())
    # ConfigParser interpolation treats percent signs specially.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return url, connect_args


target_metadata = _load_metadata()


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    _configure_database_url()
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure and execute migrations on an established connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through a synchronous callback."""
    _, connect_args = _configure_database_url()
    section = config.get_section(config.config_ini_section) or {}

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against the configured database asynchronously."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
