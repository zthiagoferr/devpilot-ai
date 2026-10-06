from fastapi import FastAPI

from app.api.agents import router as agents_router


app = FastAPI(
    title="DevPilot AI",
    description="Multi-Agent Code Intelligence Platform",
    version="0.1.0",
)

app.include_router(agents_router)


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