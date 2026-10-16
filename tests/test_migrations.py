"""Round-trip test for the Alembic migration chain.

The migrations are applied to a throwaway SQLite file — never to the configured
development or production database — so both directions of every revision are
verified, including the guarantee that existing rows survive and keep a
``NULL`` owner (there is deliberately no backfill).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

from app.core.config import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REVISION_0001 = "0001_create_analyses"
REVISION_0002 = "0002_add_analysis_user_id"


def _config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return config


def _run(db_path: Path, monkeypatch, action: str, target: str) -> None:
    """Run ``upgrade``/``downgrade`` against the throwaway database."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    try:
        if action == "upgrade":
            command.upgrade(_config(), target)
        else:
            command.downgrade(_config(), target)
    finally:
        get_settings.cache_clear()


def _columns(db_path: Path, table: str = "analyses") -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _indexes(db_path: Path, table: str = "analyses") -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(f"PRAGMA index_list({table})").fetchall()
    return {row[1] for row in rows}


def test_0002_adds_the_owner_column_and_is_reversible(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "migrations.db"

    # 1. Schema as it exists before this feature, with one pre-existing row.
    _run(db_path, monkeypatch, "upgrade", REVISION_0001)
    assert "user_id" not in _columns(db_path)

    analysis_id = uuid4().hex
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO analyses (id, task, project_name, source_code) "
            "VALUES (?, ?, ?, ?)",
            (analysis_id, "code_analysis", "legacy-project", "print('hi')\n"),
        )
        connection.commit()

    # 2. Apply the new revision: column plus index.
    _run(db_path, monkeypatch, "upgrade", "head")

    assert "user_id" in _columns(db_path)
    assert "ix_analyses_user_id" in _indexes(db_path)

    # 3. No backfill: the pre-existing row keeps a NULL owner.
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT user_id FROM analyses WHERE id = ?",
            (analysis_id,),
        ).fetchone()
    assert row == (None,)

    # 4. Downgrade removes the index and the column, keeping the data.
    _run(db_path, monkeypatch, "downgrade", REVISION_0001)

    assert "user_id" not in _columns(db_path)
    assert "ix_analyses_user_id" not in _indexes(db_path)
    with sqlite3.connect(db_path) as connection:
        remaining = connection.execute("SELECT COUNT(*) FROM analyses").fetchone()
    assert remaining == (1,)


def test_full_chain_upgrades_and_downgrades(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "chain.db"

    _run(db_path, monkeypatch, "upgrade", "head")
    assert {"id", "task", "project_name", "source_code", "user_id"} <= _columns(
        db_path
    )

    _run(db_path, monkeypatch, "downgrade", "base")

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "analyses" not in tables
