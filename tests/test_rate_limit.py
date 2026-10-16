"""In-memory rate limiting for the expensive public endpoints.

The middleware is exercised through a minimal app so the tests do not need a
database. Client identity, the proxy-header trust switch, and window expiry are
all covered explicitly.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.rate_limit import InMemoryRateLimiter, RateLimitMiddleware


def _settings(limit: int = 3, window: float = 60.0, trust: bool = False):
    return SimpleNamespace(
        rate_limit_requests=limit,
        rate_limit_window_seconds=window,
        trust_proxy_headers=trust,
    )


def _build_app(settings, limiter: InMemoryRateLimiter | None = None) -> FastAPI:
    app = FastAPI()

    @app.post("/analyses")
    async def analyses() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/repositories/load")
    async def load_repository() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter if limiter is not None else InMemoryRateLimiter(),
        settings_getter=lambda: settings,
    )
    return app


def test_default_limit_is_generous_enough_for_local_use() -> None:
    settings = Settings(_env_file=None)

    assert settings.rate_limit_requests >= 20
    assert settings.rate_limit_window_seconds > 0
    assert settings.trust_proxy_headers is False


def test_requests_below_the_limit_are_allowed() -> None:
    client = TestClient(_build_app(_settings(limit=3)))

    for _ in range(3):
        assert client.post("/analyses").status_code == 200


def test_exceeding_the_limit_returns_429_with_retry_after() -> None:
    client = TestClient(_build_app(_settings(limit=2, window=60.0)))

    assert client.post("/analyses").status_code == 200
    assert client.post("/analyses").status_code == 200

    response = client.post("/analyses")

    assert response.status_code == 429
    assert response.json() == {"detail": "Rate limit exceeded. Retry later."}
    assert int(response.headers["retry-after"]) >= 1


def test_window_expiry_restores_the_quota() -> None:
    clock = [0.0]
    limiter = InMemoryRateLimiter(time_func=lambda: clock[0])
    client = TestClient(
        _build_app(_settings(limit=1, window=10.0), limiter=limiter)
    )

    assert client.post("/analyses").status_code == 200
    assert client.post("/analyses").status_code == 429

    clock[0] = 11.0

    assert client.post("/analyses").status_code == 200


def test_different_clients_have_independent_quotas() -> None:
    app = _build_app(_settings(limit=1))
    first = TestClient(app, client=("203.0.113.10", 1111))
    second = TestClient(app, client=("203.0.113.11", 2222))

    assert first.post("/analyses").status_code == 200
    assert second.post("/analyses").status_code == 200
    assert first.post("/analyses").status_code == 429


def test_each_protected_endpoint_has_its_own_quota() -> None:
    client = TestClient(_build_app(_settings(limit=1)))

    assert client.post("/repositories/load").status_code == 200
    assert client.post("/repositories/load").status_code == 429
    # The analysis bucket is independent from the repository bucket.
    assert client.post("/analyses").status_code == 200


def test_unprotected_endpoints_are_never_throttled() -> None:
    client = TestClient(_build_app(_settings(limit=1)))

    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_zero_limit_disables_throttling() -> None:
    client = TestClient(_build_app(_settings(limit=0)))

    for _ in range(5):
        assert client.post("/analyses").status_code == 200


def test_forwarded_header_is_ignored_when_proxy_headers_untrusted() -> None:
    app = _build_app(_settings(limit=1, trust=False))
    client = TestClient(app, client=("198.51.100.7", 5000))

    assert (
        client.post(
            "/analyses", headers={"X-Forwarded-For": "1.1.1.1"}
        ).status_code
        == 200
    )
    # A different spoofed header must not grant a fresh quota to the same IP.
    assert (
        client.post(
            "/analyses", headers={"X-Forwarded-For": "2.2.2.2"}
        ).status_code
        == 429
    )


def test_last_forwarded_hop_is_used_when_proxy_headers_trusted() -> None:
    app = _build_app(_settings(limit=1, trust=True))
    # The socket address is the known reverse proxy for every request.
    client = TestClient(app, client=("10.0.0.1", 5000))
    real_client = {"X-Forwarded-For": "203.0.113.5"}

    assert client.post("/analyses", headers=real_client).status_code == 200
    assert client.post("/analyses", headers=real_client).status_code == 429

    # A different original client behind the same proxy gets its own quota.
    assert (
        client.post(
            "/analyses",
            headers={"X-Forwarded-For": "203.0.113.6"},
        ).status_code
        == 200
    )


def test_spoofed_first_hops_cannot_bypass_the_limit() -> None:
    # An appending proxy (nginx/Cloudflare/Render default) writes the observed
    # peer as the LAST entry. An attacker controls only the earlier entries, so
    # rotating them must not mint a fresh bucket.
    app = _build_app(_settings(limit=1, trust=True))
    client = TestClient(app, client=("10.0.0.1", 5000))

    assert (
        client.post(
            "/analyses",
            headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.50"},
        ).status_code
        == 200
    )
    # Same real client, different spoofed prefix: still the same quota.
    assert (
        client.post(
            "/analyses",
            headers={"X-Forwarded-For": "5.6.7.8, 203.0.113.50"},
        ).status_code
        == 429
    )


def test_invalid_forwarded_value_falls_back_to_socket_address() -> None:
    app = _build_app(_settings(limit=1, trust=True))
    client = TestClient(app, client=("192.0.2.9", 5000))
    spoofed = {"X-Forwarded-For": "not-an-ip"}

    assert client.post("/analyses", headers=spoofed).status_code == 200
    assert client.post("/analyses", headers=spoofed).status_code == 429


def test_invalid_last_hop_falls_back_to_socket_address() -> None:
    # A valid spoofed prefix with a non-IP last entry (the one the trusted
    # proxy would have appended) must not be trusted: fall back to the socket.
    app = _build_app(_settings(limit=1, trust=True))
    client = TestClient(app, client=("192.0.2.10", 5000))
    spoofed = {"X-Forwarded-For": "203.0.113.5, not-an-ip"}

    assert client.post("/analyses", headers=spoofed).status_code == 200
    assert client.post("/analyses", headers=spoofed).status_code == 429
