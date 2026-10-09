from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.agents import router as agents_router
from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router
from app.api.github import router as github_router
from app.db import session


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await session.dispose_engine()


app = FastAPI(
    title="DevPilot AI",
    description="Multi-Agent Code Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(agents_router)
app.include_router(analysis_router)
app.include_router(dashboard_router)
app.include_router(github_router)


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
    engine = session.get_engine()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
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
