"""Rate limiting for ``POST /corrections``.

The correction endpoint has its own quota so expensive AI calls can be capped
independently from analysis and repository loading. Settings objects without
the correction fields fall back to the shared ``rate_limit_*`` values.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.rate_limit import InMemoryRateLimiter, RateLimitMiddleware


def _build_app(settings, limiter: InMemoryRateLimiter | None = None) -> FastAPI:
    app = FastAPI()

    @app.post("/corrections")
    async def corrections() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/analyses")
    async def analyses() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter if limiter is not None else InMemoryRateLimiter(),
        settings_getter=lambda: settings,
    )
    return app


def test_correction_requests_are_throttled_by_their_own_limit() -> None:
    settings = SimpleNamespace(
        correction_rate_limit_requests=2,
        correction_rate_limit_window_seconds=60.0,
        rate_limit_requests=100,
        rate_limit_window_seconds=60.0,
        trust_proxy_headers=False,
    )
    client = TestClient(_build_app(settings))

    assert client.post("/corrections").status_code == 200
    assert client.post("/corrections").status_code == 200
    response = client.post("/corrections")
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1


def test_correction_limit_falls_back_to_shared_settings() -> None:
    # Older settings/tests provide only the shared attributes.
    settings = SimpleNamespace(
        rate_limit_requests=1,
        rate_limit_window_seconds=60.0,
        trust_proxy_headers=False,
    )
    client = TestClient(_build_app(settings))

    assert client.post("/corrections").status_code == 200
    assert client.post("/corrections").status_code == 429


def test_correction_and_analysis_quotas_are_independent() -> None:
    settings = SimpleNamespace(
        correction_rate_limit_requests=1,
        correction_rate_limit_window_seconds=60.0,
        rate_limit_requests=1,
        rate_limit_window_seconds=60.0,
        trust_proxy_headers=False,
    )
    client = TestClient(_build_app(settings))

    assert client.post("/corrections").status_code == 200
    assert client.post("/corrections").status_code == 429
    # The analysis bucket has not been consumed by corrections.
    assert client.post("/analyses").status_code == 200


def test_correction_window_expiry_restores_the_quota() -> None:
    clock = [0.0]
    limiter = InMemoryRateLimiter(time_func=lambda: clock[0])
    settings = SimpleNamespace(
        correction_rate_limit_requests=1,
        correction_rate_limit_window_seconds=10.0,
        rate_limit_requests=100,
        rate_limit_window_seconds=60.0,
        trust_proxy_headers=False,
    )
    client = TestClient(_build_app(settings, limiter=limiter))

    assert client.post("/corrections").status_code == 200
    assert client.post("/corrections").status_code == 429

    clock[0] = 11.0

    assert client.post("/corrections").status_code == 200


def test_zero_correction_limit_disables_correction_throttling() -> None:
    settings = SimpleNamespace(
        correction_rate_limit_requests=0,
        correction_rate_limit_window_seconds=60.0,
        rate_limit_requests=1,
        rate_limit_window_seconds=60.0,
        trust_proxy_headers=False,
    )
    client = TestClient(_build_app(settings))

    for _ in range(5):
        assert client.post("/corrections").status_code == 200


def test_default_correction_limit_is_configured() -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None)

    assert settings.correction_rate_limit_requests >= 1
    assert settings.correction_rate_limit_window_seconds > 0
