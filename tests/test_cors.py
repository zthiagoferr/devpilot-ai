"""CORS allowlist behaviour for the public API.

Cross-origin access is only enabled when ``FRONTEND_ORIGINS`` is configured,
and only for the exact origins listed there. No wildcard and no credentials.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings


REPOSITORY_FRONTEND = "https://zthiagoferr.github.io"


@pytest.fixture()
def build_app(monkeypatch):
    """Reload ``app.main`` with a specific ``FRONTEND_ORIGINS`` value."""

    def _build(origins: str | None):
        if origins is None:
            monkeypatch.delenv("FRONTEND_ORIGINS", raising=False)
        else:
            monkeypatch.setenv("FRONTEND_ORIGINS", origins)
        get_settings.cache_clear()
        import app.main as main

        importlib.reload(main)
        return main.app

    yield _build

    get_settings.cache_clear()
    import app.main as main

    importlib.reload(main)
    get_settings.cache_clear()


def _preflight(client: TestClient, origin: str, method: str = "POST"):
    return client.options(
        "/analyses",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_get_frontend_origins_is_empty_by_default() -> None:
    assert Settings(_env_file=None).get_frontend_origins() == []


def test_get_frontend_origins_splits_strips_and_drops_blanks() -> None:
    settings = Settings(
        _env_file=None,
        frontend_origins=" https://a.example , ,https://b.example ",
    )

    assert settings.get_frontend_origins() == [
        "https://a.example",
        "https://b.example",
    ]


def test_preflight_allows_the_exact_configured_origin(build_app) -> None:
    app = build_app(REPOSITORY_FRONTEND)

    response = _preflight(TestClient(app), REPOSITORY_FRONTEND)

    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == REPOSITORY_FRONTEND
    )
    assert "access-control-allow-credentials" not in response.headers
    assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_preflight_rejects_a_third_party_origin(build_app) -> None:
    app = build_app(REPOSITORY_FRONTEND)

    response = _preflight(TestClient(app), "https://attacker.example")

    assert "access-control-allow-origin" not in response.headers
    assert response.headers.get("access-control-allow-origin") != "*"


def test_preflight_supports_multiple_configured_origins(build_app) -> None:
    app = build_app(f"https://a.example,{REPOSITORY_FRONTEND}")
    client = TestClient(app)

    for origin in ("https://a.example", REPOSITORY_FRONTEND):
        response = _preflight(client, origin)
        assert response.headers.get("access-control-allow-origin") == origin


def test_preflight_allows_the_authorization_header(build_app) -> None:
    """The browser only sends ``Authorization`` when the preflight allows it.

    Without ``Authorization`` in ``Access-Control-Allow-Headers`` every
    authenticated request from the published frontend fails before it is sent.
    """
    app = build_app(REPOSITORY_FRONTEND)

    response = TestClient(app).options(
        "/analyses",
        headers={
            "Origin": REPOSITORY_FRONTEND,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed
    assert "content-type" in allowed


def test_no_cors_middleware_when_origins_are_not_configured(build_app) -> None:
    app = build_app(None)

    assert not any(
        middleware.cls is CORSMiddleware for middleware in app.user_middleware
    )

    response = _preflight(TestClient(app), REPOSITORY_FRONTEND)
    assert "access-control-allow-origin" not in response.headers
