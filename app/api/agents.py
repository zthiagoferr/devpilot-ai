from fastapi import APIRouter, HTTPException

from app.agents.code_agent import CodeAgent
from app.agents.orchestrator import OrchestratorAgent
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
    agent = CodeAgent()

    result = await agent.execute(
        {
            "project_name": request.project_name,
            "source_code": request.source_code,
        }
    )

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
        }
    )

    if result["status"] == "error":
        raise HTTPException(
            status_code=400,
            detail=result["message"],
        )

    return OrchestratorResponse(**result)