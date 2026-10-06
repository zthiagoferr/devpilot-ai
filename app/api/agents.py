from fastapi import APIRouter
from app.agents.orchestrator import OrchestratorAgent
from app.agents.code_agent import CodeAgent
from app.schemas.analysis import CodeAnalysisRequest, CodeAnalysisResult


router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)


@router.get("/orchestrator")
async def orchestrator_status() -> dict:
    orchestrator = OrchestratorAgent()

    return await orchestrator.execute(
        {
            "project": "devpilot-ai",
            "action": "initialize",
        }
    )

@router.post("/code", response_model=CodeAnalysisResult)
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