import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.agents import router as agents_router
from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router
from app.core.config import get_settings
from app.core.logging import install_sqlalchemy_parameter_redaction
from app.core.rate_limit import InMemoryRateLimiter, RateLimitMiddleware
from app.db import session

logger = logging.getLogger("devpilot")

try:
    from app.api.github import router as github_router
except ModuleNotFoundError:
    github_router = None
    logger.warning(
        "GitHub routes are unavailable because an optional dependency is "
        "missing; the application will start without them.",
        exc_info=True,
    )

try:
    from app.api.corrections import router as corrections_router
except ModuleNotFoundError:
    corrections_router = None
    logger.warning(
        "Correction routes are unavailable because an optional dependency is "
        "missing; the application will start without them.",
        exc_info=True,
    )


# Upper bound, in seconds, for the readiness database probe. Kept short so an
# unreachable database fails ``/ready`` quickly without hanging the request.
READINESS_TIMEOUT_SECONDS = 5.0


def _configure_logging() -> int:
    """Configure root logging from settings and return the effective level."""
    settings = get_settings()
    level_name = settings.log_level.strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
    )
    logging.getLogger().setLevel(level)
    # SQLAlchemy can render bound parameters (analyzed user code) in its log
    # records. Install the redaction after the handlers exist so both direct
    # SQLAlchemy logs and records propagated to the root handlers are covered.
    install_sqlalchemy_parameter_redaction()
    return level


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging()
    logger.info(
        "Starting DevPilot AI (environment=%s, database_configured=%s)",
        settings.environment,
        settings.get_database_url() is not None,
    )
    yield
    logger.info("Shutting down DevPilot AI")
    await session.dispose_engine()


# Install the redaction at import time too: handlers can exist before the
# lifespan runs (uvicorn configures logging before importing the app), and the
# application must stay protected with ``--lifespan off`` or when a TestClient
# is used without a context manager. The lifespan re-installs it to cover
# handlers created later.
install_sqlalchemy_parameter_redaction()


app = FastAPI(
    title="DevPilot AI",
    description="Multi-Agent Code Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(agents_router)
app.include_router(analysis_router)
app.include_router(dashboard_router)

if github_router is not None:
    app.include_router(github_router)

if corrections_router is not None:
    app.include_router(corrections_router)


# Rate limiting is applied first so CORS (added below) stays the outermost
# middleware and can annotate throttling responses with the correct headers.
_rate_limiter = InMemoryRateLimiter()
app.add_middleware(RateLimitMiddleware, limiter=_rate_limiter)

# Cross-origin access is opt-in and limited to the exact configured origins.
# ``*`` and credentialed cross-origin requests are intentionally not allowed.
_frontend_origins = get_settings().get_frontend_origins()
if _frontend_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Authorization"],
    )


project_root = Path(__file__).resolve().parent.parent
web_directory = project_root / "web"
if not web_directory.is_dir():
    web_directory = Path(__file__).resolve().parent / "web"

app.mount("/static", StaticFiles(directory=web_directory), name="static")


@app.get("/", tags=["System"])
async def root() -> dict[str, str]:
    return {
        "name": "DevPilot AI",
        "message": "Multi-Agent Code Intelligence Platform",
    }


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "devpilot-ai",
    }


async def check_database_readiness() -> bool:
    """Probe the configured database with one bounded ``SELECT 1``.

    The query runs on the active engine and is wrapped in a short timeout so a
    hung or unreachable database fails readiness quickly instead of stalling the
    request. Connection details are never returned by the caller.
    """

    async def _probe() -> None:
        engine = session.get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    await asyncio.wait_for(_probe(), timeout=READINESS_TIMEOUT_SECONDS)
    return True


@app.get("/ready", tags=["System"])
async def readiness_check() -> dict[str, str]:
    try:
        ready = await check_database_readiness()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database readiness check failed.",
        )

    if not ready:
        raise HTTPException(
            status_code=503,
            detail="Database readiness check failed.",
        )

    return {
        "status": "ready",
        "service": "devpilot-ai",
    }
