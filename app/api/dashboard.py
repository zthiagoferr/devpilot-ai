from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter()

_DASHBOARD_PATH = Path(__file__).resolve().parents[2] / "web" / "dashboard.html"


@router.get("/dashboard", response_class=FileResponse)
async def dashboard() -> FileResponse:
    """Serve the dashboard web page."""
    return FileResponse(_DASHBOARD_PATH)
