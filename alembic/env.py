"""Alembic environment configuration.

The persistence metadata is imported without importing the application entrypoint or
creating a database engine. Engines are created only when online migrations run.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config


config = context.config


def _load_metadata() -> Any:
    """Load the persistence metadata without initializing a database connection."""
    metadata = None
    base = None

    for module_name in (
        "app.persistence.database",
        "app.persistence.base",
        "app.persistence.models",
    ):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            continue

        if base is None:
            base = getattr(module, "Base", None)
        metadata = getattr(module, "metadata", metadata)
        metadata = getattr(module, "target_metadata", metadata)

        if base is not None and hasattr(base, "metadata"):
            metadata = base.metadata
            break

    if metadata is None:
        raise ImportError(
            "Could not locate persistence metadata. Expected a Base.metadata "
            "or metadata object in app.persistence."
        )

    return metadata


def _get_database_url() -> str:
    """Return the unredacted database URL used by Alembic."""
    config_module = importlib.import_module("app.core.config")
    get_settings = getattr(config_module, "get_settings")

    try:
        settings = get_settings(redact_secrets=False)
    except TypeError:
        settings = get_settings()

    accessor = getattr(settings, "get_database_url", None)
    if accessor is not None:
        try:
            return str(accessor(redact=False))
        except TypeError:
            return str(accessor())

    return str(settings.database_url)


def _configure_database_url() -> None:
    """Put the settings URL into Alembic's configuration."""
    url = _get_database_url()
    # ConfigParser interpolation treats percent signs specially.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


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
    _configure_database_url()
    section = config.get_section(config.config_ini_section) or {}

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
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
