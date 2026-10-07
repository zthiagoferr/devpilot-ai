import pytest
from fastapi.testclient import TestClient

import app.main
import app.db.session as database_session
from app.core.config import Settings


def test_readiness_returns_ready_when_database_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ready() -> bool:
        return True

    monkeypatch.setattr(app.main, "check_database_readiness", ready)

    with TestClient(app.main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "devpilot-ai",
    }


def test_readiness_does_not_expose_database_errors_or_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = "postgresql+asyncpg://fake_user:fake_password@example.invalid/fake_db"
    username = "fake_user"
    password = "fake_password"
    diagnostic = "fake database diagnostic text"

    async def unavailable() -> bool:
        raise RuntimeError(
            f"{diagnostic}: {database_url} username={username} password={password}"
        )

    monkeypatch.setattr(app.main, "check_database_readiness", unavailable)

    with TestClient(app.main.app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    for secret in (database_url, username, password, diagnostic):
        assert secret not in response.text


def test_liveness_is_healthy_without_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def database_must_not_be_called() -> bool:
        raise AssertionError("liveness must not access the database")

    monkeypatch.setattr(
        app.main,
        "check_database_readiness",
        database_must_not_be_called,
    )

    with TestClient(app.main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "devpilot-ai",
    }


def test_production_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database_session, "DATABASE_URL", None)

    with pytest.raises(RuntimeError):
        database_session._configured_database_url()


def test_production_rejects_sqlite_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(RuntimeError):
        database_session._normalise_and_validate_url(
            "sqlite+aiosqlite:///./test.db"
        )


def test_development_accepts_sqlite_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    database_url = "sqlite+aiosqlite:///./test.db"

    assert database_session._normalise_and_validate_url(database_url) == (
        database_url,
        False,
    )


def test_settings_secret_values_remain_masked() -> None:
    database_url = "postgresql+asyncpg://user:password@example.invalid/app"
    api_key = "fake-api-key"
    settings = Settings(database_url=database_url, llm_api_key=api_key)

    assert str(settings.database_url) == "**********"
    assert str(settings.llm_api_key) == "**********"
    assert settings.database_url.get_secret_value() == database_url
    assert settings.llm_api_key.get_secret_value() == api_key
    assert database_url not in repr(settings)
    assert api_key not in repr(settings)
