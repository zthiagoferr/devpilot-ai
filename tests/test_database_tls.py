"""Unit tests for database URL normalisation and libpq TLS translation.

These tests never open a connection: they validate the URL/connect-args
translation that both the application engine and Alembic rely on.
"""

from __future__ import annotations

import app.db.session as db_session


def test_bare_postgres_url_is_normalised_to_asyncpg() -> None:
    url, is_postgresql = db_session._normalise_and_validate_url(
        "postgresql://user:pass@host:5432/db"
    )

    assert is_postgresql is True
    assert url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_sslmode_is_stripped_from_the_validated_url() -> None:
    url, is_postgresql = db_session._normalise_and_validate_url(
        "postgresql://user:pass@host/db?sslmode=require"
    )

    assert is_postgresql is True
    assert url.startswith("postgresql+asyncpg://")
    assert "sslmode" not in url


def test_prepare_async_url_translates_sslmode_to_ssl() -> None:
    url, connect_args = db_session.prepare_async_url(
        "postgresql://user:pass@ep-x.neon.tech/db?sslmode=require"
    )

    assert url == "postgresql+asyncpg://user:pass@ep-x.neon.tech/db"
    assert connect_args == {"ssl": "require"}


def test_prepare_async_url_drops_channel_binding() -> None:
    url, connect_args = db_session.prepare_async_url(
        "postgresql://user:pass@ep-x.neon.tech/db"
        "?sslmode=require&channel_binding=require"
    )

    assert "sslmode" not in url
    assert "channel_binding" not in url
    assert connect_args == {"ssl": "require"}


def test_prepare_async_url_leaves_sqlite_unchanged() -> None:
    assert db_session.prepare_async_url("sqlite+aiosqlite:///./dev.db") == (
        "sqlite+aiosqlite:///./dev.db",
        {},
    )


def test_prepare_async_url_keeps_unrelated_query_parameters() -> None:
    url, connect_args = db_session.prepare_async_url(
        "postgresql+asyncpg://user:pass@host/db?application_name=devpilot"
    )

    assert connect_args == {}
    assert "application_name=devpilot" in url


def test_get_engine_forwards_translated_ssl_connect_args(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(
        db_session,
        "_configured_database_url",
        lambda: "postgresql://user:pass@ep-x.neon.tech/db?sslmode=require",
    )
    monkeypatch.setattr(db_session, "create_async_engine", fake_create_engine)

    db_session._engine = None
    try:
        db_session.get_engine()
    finally:
        db_session._engine = None

    assert captured["url"] == "postgresql+asyncpg://user:pass@ep-x.neon.tech/db"
    assert captured["kwargs"]["connect_args"] == {"ssl": "require"}  # type: ignore[index]
    assert captured["kwargs"]["echo"] is False  # type: ignore[index]
