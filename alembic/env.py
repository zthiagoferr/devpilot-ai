"""Alembic environment configuration.

The persistence metadata is imported directly from the application models, and
the database URL comes from the same configuration object the application uses
(:mod:`app.core.config` / :mod:`app.db.session`).  Engines are created only when
online migrations run.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.db.models import Base
from app.db.session import _configured_database_url, _normalise_and_validate_url


config = context.config

target_metadata = Base.metadata


def _get_database_url() -> str:
    """Return the async database URL used by the application."""
    configured = _configured_database_url()
    url, _ = _normalise_and_validate_url(configured)
    return url


def _configure_database_url() -> None:
    """Put the application database URL into Alembic's configuration."""
    url = _get_database_url()
    # ConfigParser interpolation treats percent signs specially.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


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
