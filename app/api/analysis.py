from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, require_user
from app.core.auth import VerifiedUser
from app.db.repositories import AnalysisRepository
from app.db.session import get_db_session
from app.schemas.analysis import AnalysisCreate, AnalysisResponse
from app.services.analysis import (
    AnalysisExecutionError,
    AnalysisService,
    InvalidAnalysisTaskError,
    SourceCodeTooLargeError,
)


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
    user: VerifiedUser | None = Depends(get_optional_user),
) -> AnalysisResponse:
    """Create an analysis.

    Anonymous submissions stay supported (the visitor flow is public). A valid
    bearer token only adds ownership: the uid is taken from the verified token,
    never from the body. A present-but-invalid token is a ``401``.
    """
    try:
        result = await service.create_analysis(
            analysis,
            user_id=user.uid if user is not None else None,
        )
    except InvalidAnalysisTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SourceCodeTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except AnalysisExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return _serialize_analysis(result)


@router.get("", response_model=list[AnalysisResponse])
async def list_analyses(
    limit: int = Query(default=20, ge=1, le=100),
    service: AnalysisService = Depends(get_analysis_service),
    user: VerifiedUser = Depends(require_user),
) -> list[AnalysisResponse]:
    """List the authenticated caller's own analyses, newest first."""
    results = await service.list_analyses(limit=limit, user_id=user.uid)
    return [_serialize_analysis(result) for result in results]


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: UUID,
    service: AnalysisService = Depends(get_analysis_service),
    user: VerifiedUser = Depends(require_user),
) -> AnalysisResponse:
    """Return one of the caller's own analyses; another user's is a ``404``."""
    result = await service.get_analysis(analysis_id, user_id=user.uid)

    if result is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return _serialize_analysis(result)
