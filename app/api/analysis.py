"""Analysis API: run analyses and read persisted history.

``POST /analyses`` runs the requested task through the orchestrator and persists
the produced payload.  ``GET /analyses`` and ``GET /analyses/{id}`` read the
persisted records.  All endpoints use the real service, repository and database.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.insights_agent import InsightsAgent
from app.agents.orchestrator import OrchestratorAgent
from app.core.config import get_settings
from app.db.repositories import AnalysisRepository
from app.db.session import get_db_session
from app.llm.factory import create_llm_provider
from app.schemas.analysis import AnalysisCreate, AnalysisResponse
from app.services.analysis import AnalysisService
from app.services.llm_service import LLMService


router = APIRouter(prefix="/analyses", tags=["analyses"])


async def get_analysis_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AnalysisRepository:
    return AnalysisRepository(session)


async def get_analysis_service(
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> AnalysisService:
    return AnalysisService(repository)


def get_orchestrator() -> OrchestratorAgent:
    """Build the orchestrator with the configured LLM provider and insights."""
    llm_service = LLMService(create_llm_provider(get_settings()))
    return OrchestratorAgent(insights_agent=InsightsAgent(llm_service))


def _serialize_analysis(analysis: Any) -> AnalysisResponse:
    return AnalysisResponse.model_validate(analysis)


@router.post("", response_model=AnalysisResponse, status_code=201)
async def create_analysis(
    request: AnalysisCreate,
    service: AnalysisService = Depends(get_analysis_service),
    orchestrator: OrchestratorAgent = Depends(get_orchestrator),
) -> AnalysisResponse:
    outcome = await orchestrator.execute(
        {
            "task": request.task,
            "project_name": request.project_name,
            "source_code": request.source_code,
        }
    )

    if outcome.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail=outcome.get("message", "Analysis could not be completed."),
        )

    payload = outcome.get("result", outcome)
    analysis = await service.create_analysis(
        task=request.task,
        project_name=request.project_name,
        source_code=request.source_code,
        result=payload,
        status=str(outcome.get("status", "completed")),
    )
    return _serialize_analysis(analysis)


@router.get("", response_model=list[AnalysisResponse])
async def list_analyses(
    limit: int = Query(default=AnalysisRepository.DEFAULT_LIMIT, ge=1, le=AnalysisRepository.MAX_LIMIT),
    service: AnalysisService = Depends(get_analysis_service),
) -> list[AnalysisResponse]:
    results = await service.list_analyses(limit=limit)
    return [_serialize_analysis(result) for result in results]


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: UUID,
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisResponse:
    result = await service.get_analysis(analysis_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return _serialize_analysis(result)
