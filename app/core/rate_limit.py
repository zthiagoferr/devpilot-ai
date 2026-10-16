"""In-memory rate limiting for the expensive public API endpoints.

Only the standard library is used: no external store or dependency is added.
State is process-local, so it resets on restart and is not shared across
workers; scaling the backend beyond a single worker would require an external
store, which is intentionally out of scope for the first public version.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings

# Endpoints that trigger expensive work (analysis orchestration, GitHub
# downloads) and are therefore the only ones throttled. Paths are matched
# exactly after normalising a trailing slash.
PROTECTED_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/analyses"),
        ("POST", "/repositories/load"),
    }
)


class InMemoryRateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string.

    A key may make at most ``limit`` requests per ``window`` seconds. Hit
    timestamps are pruned lazily on every check, so an expired window frees the
    quota automatically. A lock keeps the counter consistent when a single
    worker handles concurrent requests.
    """

    def __init__(self, time_func: Callable[[], float] = time.monotonic) -> None:
        self._time = time_func
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float) -> tuple[bool, float]:
        """Record one request and report whether it is allowed.

        Returns ``(allowed, retry_after)``. ``retry_after`` is the number of
        seconds until the oldest hit leaves the window and is ``0.0`` when the
        request is allowed.
        """
        if window <= 0:
            window = 0.0
        now = self._time()

        with self._lock:
            timestamps = [
                hit for hit in self._hits.get(key, []) if now - hit < window
            ]
            if len(timestamps) >= limit:
                retry_after = window - (now - timestamps[0])
                self._hits[key] = timestamps
                return False, max(retry_after, 0.0)

            timestamps.append(now)
            self._hits[key] = timestamps
            return True, 0.0

    def reset(self) -> None:
        """Drop every recorded hit. Used to isolate tests and window resets."""
        with self._lock:
            self._hits.clear()


def resolve_client_identifier(
    request: Request,
    *,
    trust_proxy_headers: bool,
) -> str:
    """Return the client identity used as the rate-limit key.

    When ``trust_proxy_headers`` is false the socket address is authoritative
    and ``X-Forwarded-For`` is ignored, because a client that reaches the
    application directly could forge it. When it is true the application is
    assumed to sit behind exactly one known reverse proxy that *appends* the
    observed peer address to ``X-Forwarded-For`` (the behaviour of
    ``proxy_add_x_forwarded_for`` in nginx/Cloudflare/Render). In that case the
    **last** entry is the hop the trusted proxy appended; every earlier entry
    was supplied by the client and is therefore spoofable, so using the first
    entry would let an attacker mint a fresh rate-limit bucket per request. The
    forwarded value is only trusted when it parses as an IP address; anything
    else falls back to the socket address.
    """
    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            candidate = forwarded.split(",")[-1].strip()
            try:
                ipaddress.ip_address(candidate)
            except ValueError:
                pass
            else:
                return candidate

    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


def _normalise_path(path: str) -> str:
    stripped = path.rstrip("/")
    return stripped or "/"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply an :class:`InMemoryRateLimiter` to the protected endpoints."""

    def __init__(
        self,
        app: Any,
        *,
        limiter: InMemoryRateLimiter | None = None,
        settings_getter: Callable[[], Any] = get_settings,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter if limiter is not None else InMemoryRateLimiter()
        self._settings_getter = settings_getter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Any:
        key_path = _normalise_path(request.url.path)
        if (request.method, key_path) not in PROTECTED_PATHS:
            return await call_next(request)

        settings = self._settings_getter()
        limit = int(getattr(settings, "rate_limit_requests", 0) or 0)
        if limit <= 0:
            # A non-positive limit disables throttling entirely.
            return await call_next(request)

        window = float(getattr(settings, "rate_limit_window_seconds", 0.0) or 0.0)
        client = resolve_client_identifier(
            request,
            trust_proxy_headers=bool(
                getattr(settings, "trust_proxy_headers", False)
            ),
        )
        bucket = f"{request.method}:{key_path}:{client}"

        allowed, retry_after = self._limiter.check(bucket, limit, window)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Retry later."},
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )

        return await call_next(request)
