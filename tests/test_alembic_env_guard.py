"""Production guard for Alembic database URLs.

The guard must reject any non-PostgreSQL URL in production *before* a migration
runs and before SQLite can create a local file. The error message is fixed and
never contains the original URL, driver, host, user, or password.

Integration cases run ``alembic`` in a subprocess with ``cwd`` pointing at a
temporary directory, so the repository ``.env`` and the caller environment
cannot influence the result. No real database is touched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.db.session import _PRODUCTION_DATABASE_URL_ERROR, validate_migration_database_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
EXPECTED_ERROR = (
    "DATABASE_URL must be configured with a PostgreSQL URL in production."
)


def _run_alembic(
    tmp_path: Path,
    args: tuple[str, ...],
    *,
    environment: str | None,
    database_url: str | None,
    pythonpath: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Alembic in isolation from the repository ``.env`` and shell."""
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("ENVIRONMENT", None)
    if environment is not None:
        env["ENVIRONMENT"] = environment
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    if pythonpath is not None:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(pythonpath)
            if not existing
            else os.pathsep.join((str(pythonpath), existing))
        )

    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("environment", ["production", "Production", "prod"])
def test_production_rejects_sqlite_environment_names(environment: str) -> None:
    secret_url = "sqlite+aiosqlite:///./dev.db"

    with pytest.raises(RuntimeError) as excinfo:
        validate_migration_database_url(secret_url, environment)

    message = str(excinfo.value)
    assert message == EXPECTED_ERROR
    assert secret_url not in message
    assert "sqlite" not in message.lower()
    assert "dev.db" not in message


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:secret@host.example/db",
        "postgres://user:secret@host.example/db",
        "postgresql+asyncpg://user:secret@host.example/db",
    ],
)
def test_production_accepts_postgresql_urls(database_url: str) -> None:
    assert validate_migration_database_url(database_url, "production") == database_url


@pytest.mark.parametrize("environment", [None, "development", "Development", "staging"])
def test_non_production_returns_the_url_unchanged(environment: str | None) -> None:
    database_url = "sqlite+aiosqlite:///./dev.db"

    assert validate_migration_database_url(database_url, environment) == database_url


@pytest.mark.parametrize("database_url", ["", "   ", "not-a-url", "mysql://h/db"])
def test_production_rejects_invalid_urls_with_the_fixed_message(
    database_url: str,
) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        validate_migration_database_url(database_url, "production")

    assert str(excinfo.value) == EXPECTED_ERROR


def test_production_without_url_fails_and_creates_no_sqlite_file(
    tmp_path: Path,
) -> None:
    result = _run_alembic(
        tmp_path,
        ("upgrade", "head"),
        environment="production",
        database_url=None,
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert EXPECTED_ERROR in output
    assert not (tmp_path / "dev.db").exists()


def test_production_with_sqlite_url_fails_and_creates_no_file(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'guarded.db'}"

    result = _run_alembic(
        tmp_path,
        ("upgrade", "head"),
        environment="production",
        database_url=database_url,
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert EXPECTED_ERROR in output
    assert database_url not in output
    assert not (tmp_path / "guarded.db").exists()


def test_production_offline_sql_upgrade_is_blocked(tmp_path: Path) -> None:
    result = _run_alembic(
        tmp_path,
        ("upgrade", "head", "--sql"),
        environment="production",
        database_url=None,
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert EXPECTED_ERROR in output
    assert not (tmp_path / "dev.db").exists()


def test_development_without_url_still_runs_migrations(tmp_path: Path) -> None:
    result = _run_alembic(
        tmp_path,
        ("upgrade", "head"),
        environment="development",
        database_url=None,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dev.db").exists()


def test_production_fails_closed_when_session_module_cannot_be_imported(
    tmp_path: Path,
) -> None:
    """A broken ``app.db.session`` import must not silently skip the guard.

    ``sitecustomize`` poisons ``sys.modules`` in the child interpreter so the
    lazy import inside ``alembic/env.py`` raises ``ImportError``. Production
    must still fail with the fixed message and create no SQLite file.
    """
    (tmp_path / "sitecustomize.py").write_text(
        "import sys\n\nsys.modules['app.db.session'] = None\n",
        encoding="utf-8",
    )
    secret_url = "sqlite+aiosqlite:///./dev.db"

    result = _run_alembic(
        tmp_path,
        ("upgrade", "head"),
        environment="production",
        database_url=secret_url,
        pythonpath=tmp_path,
    )

    output = f"{result.stdout}\n{result.stderr}"
    assert EXPECTED_ERROR == _PRODUCTION_DATABASE_URL_ERROR
    assert result.returncode != 0
    assert EXPECTED_ERROR in output
    assert secret_url not in output
    assert not (tmp_path / "dev.db").exists()
