from typing import Any

from fastapi import APIRouter, HTTPException

from app.agents.orchestrator import OrchestratorAgent
from app.languages.detector import detect_language
from app.schemas.analysis import (
    AnalysisRequest,
    CodeAnalysisRequest,
    CodeAnalysisResult,
    OrchestratorResponse,
    OrchestratorStatus,
)


router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)


@router.get(
    "/orchestrator",
    response_model=OrchestratorStatus,
)
async def orchestrator_status() -> OrchestratorStatus:
    orchestrator = OrchestratorAgent()

    return OrchestratorStatus(
        agent=orchestrator.name,
        responsibility=orchestrator.responsibility,
        status="ready",
    )


@router.post(
    "/code",
    response_model=CodeAnalysisResult,
)
async def analyze_code(
    request: CodeAnalysisRequest,
) -> CodeAnalysisResult:
    orchestrator = OrchestratorAgent()
    detection = detect_language(
        request.source_code,
        path=request.file_path,
        requested=request.language,
    )

    orchestration = await orchestrator.execute(
        {
            "task": "code",
            "project_name": request.project_name,
            "source_code": request.source_code,
            "language": request.language,
            "file_path": request.file_path,
            "detection": detection,
            "protheus_version": request.protheus_version,
        }
    )

    payload = orchestration.get("result")
    if not isinstance(payload, dict):
        # The orchestrator never routes ``code`` to an error for a valid
        # request, but keeping the legacy shape is safer than failing here.
        payload = {
            "agent": orchestration.get("agent", "orchestrator"),
            "status": orchestration.get("status"),
            "message": orchestration.get("message"),
        }
    result: dict[str, Any] = dict(payload)
    result.setdefault("language", detection.language)
    result.setdefault("language_source", detection.source)
    result["confidence"] = round(float(detection.confidence), 2)
    result.setdefault("project_name", request.project_name)

    return CodeAnalysisResult(**result)


@router.post(
    "/orchestrate",
    response_model=OrchestratorResponse,
)
async def orchestrate_analysis(
    request: AnalysisRequest,
) -> OrchestratorResponse:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": request.task,
            "project_name": request.project_name,
            "source_code": request.source_code,
            "language": request.language,
            "file_path": request.file_path,
            "protheus_version": request.protheus_version,
        }
    )

    if result["status"] == "error":
        raise HTTPException(
            status_code=400,
            detail=result["message"],
        )

    return OrchestratorResponse(**result)
