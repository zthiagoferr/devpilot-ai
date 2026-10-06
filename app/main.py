from fastapi import FastAPI

from app.api.agents import router as agents_router
from app.api.analysis import router as analysis_router

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

if github_router is not None:
    app.include_router(github_router)


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
