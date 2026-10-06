from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import AnalysisRepository
from app.db.session import get_db_session
from app.schemas.analysis import AnalysisCreate, AnalysisResponse
from app.services.analysis import AnalysisService


router = APIRouter(prefix="/analyses", tags=["analyses"])


async def get_analysis_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AnalysisRepository:
    return AnalysisRepository(session)


async def get_analysis_service(
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> AnalysisService:
    return AnalysisService(repository)


def _serialize_analysis(analysis: Any) -> AnalysisResponse:
    return AnalysisResponse.model_validate(analysis)


@router.post("", response_model=AnalysisResponse, status_code=201)
async def create_analysis(
    analysis: AnalysisCreate,
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisResponse:
    result = await service.create_analysis(analysis)
    return _serialize_analysis(result)


@router.get("", response_model=list[AnalysisResponse])
async def list_analyses(
    limit: int = Query(default=20, ge=1, le=100),
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
