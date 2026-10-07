from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.agents import router as agents_router
from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router

try:
    from app.api.github import router as github_router
except ModuleNotFoundError:
    github_router = None


app = FastAPI(
    title="DevPilot AI",
    description="Multi-Agent Code Intelligence Platform",
    version="0.1.0",
)

app.include_router(agents_router)
app.include_router(analysis_router)
app.include_router(dashboard_router)

if github_router is not None:
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
