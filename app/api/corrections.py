"""AI correction API.

The endpoints only expose persisted, owner-scoped corrections. Nothing is
executed, and approving a correction never mutates the related analysis or any
remote repository. Provider failures are translated into sanitized responses;
source code, prompts, and credentials never reach logs or error bodies.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analysis import get_analysis_repository
from app.api.deps import get_optional_user, require_user
from app.core.auth import VerifiedUser
from app.core.config import Settings, get_settings
from app.db.repositories import AnalysisRepository, CorrectionRepository
from app.db.session import get_db_session
from app.languages.base import UnsupportedLanguageError
from app.llm.factory import create_llm_provider
from app.schemas.correction import (
    CorrectionBatchCreate,
    CorrectionBatchResponse,
    CorrectionCreate,
    CorrectionDecision,
    CorrectionResponse,
)
from app.services.correction_batch_service import CorrectionBatchService
from app.services.correction_errors import (
    CorrectionBatchInvalidPathError,
    CorrectionBatchTooLargeError,
    CorrectionBatchTooManyFilesError,
    CorrectionBatchUnsupportedFileError,
    CorrectionInvalidResponseError,
    CorrectionNoIssuesError,
    CorrectionNotFoundError,
    CorrectionProviderError,
    CorrectionSafetyError,
    CorrectionSourceTooLargeError,
    CorrectionStateError,
    CorrectionTimeoutError,
    CorrectionTooManyIssuesError,
    CorrectionUnavailableError,
)
from app.services.correction_service import CorrectionService, serialize_correction
from app.services.llm_service import LLMService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/corrections", tags=["corrections"])

NOT_CONFIGURED_DETAIL = "AI correction is not configured on this server."
NOT_CONFIGURED_PROVIDER_DETAIL = (
    "AI correction is not configured: set LLM_PROVIDER and LLM_API_KEY."
)


async def get_correction_repository(
    session: AsyncSession = Depends(get_db_session),
) -> CorrectionRepository:
    return CorrectionRepository(session)


async def get_correction_llm(
    settings: Settings = Depends(get_settings),
) -> LLMService:
    """Build the correction provider, answering ``503`` when unavailable.

    The deterministic fake provider is opt-in: with ``LLM_PROVIDER=fake`` and
    ``CORRECTION_FAKE_PROVIDER_ENABLED`` unset the endpoint stays disabled so a
    development default never persists fake "corrected" code.
    """
    if (
        settings.llm_provider == "fake"
        and not settings.correction_fake_provider_enabled
    ):
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED_DETAIL)

    try:
        provider = create_llm_provider(settings)
    except ValueError:
        raise HTTPException(
            status_code=503,
            detail=NOT_CONFIGURED_PROVIDER_DETAIL,
        ) from None

    return LLMService(provider)


async def get_correction_service(
    repository: CorrectionRepository = Depends(get_correction_repository),
    analyses: AnalysisRepository = Depends(get_analysis_repository),
    llm: LLMService = Depends(get_correction_llm),
    settings: Settings = Depends(get_settings),
) -> CorrectionService:
    provider_name = settings.llm_provider if settings.llm_provider else None
    return CorrectionService(
        repository,
        analyses,
        llm,
        settings=settings,
        provider_name=provider_name,
    )


async def get_correction_batch_service(
    service: CorrectionService = Depends(get_correction_service),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
) -> CorrectionBatchService:
    # The same request session used by the repositories: the batch commits
    # after each completed file so a later persistence failure preserves them.
    return CorrectionBatchService(service, session=session, settings=settings)


@router.post("", response_model=CorrectionResponse, status_code=201)
async def create_correction(
    request: CorrectionCreate,
    service: CorrectionService = Depends(get_correction_service),
    user: VerifiedUser | None = Depends(get_optional_user),
) -> CorrectionResponse:
    """Request one AI correction.

    Anonymous submissions are accepted but never readable afterwards; a valid
    bearer token adds ownership and allows referencing one of the caller's own
    analyses.
    """
    try:
        correction = await service.create(
            request,
            user_id=user.uid if user is not None else None,
        )
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except (CorrectionTooManyIssuesError, CorrectionNoIssuesError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except CorrectionSourceTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except CorrectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except CorrectionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CorrectionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except CorrectionTimeoutError:
        # Only the error type and the request size are logged; the source code,
        # the prompt, and the provider payload never reach the logs.
        logger.warning(
            "correction timed out status=504 source_bytes=%d",
            len(request.source_code.encode("utf-8")),
        )
        raise HTTPException(
            status_code=504,
            detail="The AI provider timed out. Try a smaller file or try again.",
        ) from None
    except CorrectionInvalidResponseError:
        logger.warning(
            "correction invalid response status=502 source_bytes=%d",
            len(request.source_code.encode("utf-8")),
        )
        raise HTTPException(
            status_code=502,
            detail="The AI provider returned an invalid response.",
        ) from None
    except CorrectionSafetyError:
        logger.warning(
            "correction rejected by safety checks status=422 source_bytes=%d",
            len(request.source_code.encode("utf-8")),
        )
        raise HTTPException(
            status_code=422,
            detail="The proposed correction was rejected by safety checks.",
        ) from None
    except CorrectionProviderError:
        logger.warning(
            "correction provider error status=502 source_bytes=%d",
            len(request.source_code.encode("utf-8")),
        )
        raise HTTPException(
            status_code=502,
            detail="The AI provider returned an unusable correction.",
        ) from None

    return serialize_correction(correction)


@router.post("/batch", response_model=CorrectionBatchResponse, status_code=200)
async def create_correction_batch(
    request: CorrectionBatchCreate,
    service: CorrectionBatchService = Depends(get_correction_batch_service),
    user: VerifiedUser | None = Depends(get_optional_user),
) -> CorrectionBatchResponse:
    """Request AI corrections for a small set of files in one call.

    The batch is a dedicated route instead of a second response shape on
    ``POST /corrections``: a union response would change the OpenAPI schema of
    the existing endpoint and break generated clients. Each completed file is
    persisted as its own pending correction, so the per-file decision endpoint
    keeps full ownership of approval. Files that fail or are skipped do not
    discard the corrections already completed.

    Only request-wide problems abort the call (``422`` limits/path/language,
    ``404`` foreign analysis, ``503`` no provider, ``429`` rate limit). A
    per-file failure is reported inside ``results`` with its own sanitized
    status so the caller still receives the successful files.
    """
    try:
        return await service.create_batch(
            request,
            user_id=user.uid if user is not None else None,
        )
    except UnsupportedLanguageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except (
        CorrectionBatchTooManyFilesError,
        CorrectionBatchTooLargeError,
        CorrectionBatchInvalidPathError,
        CorrectionBatchUnsupportedFileError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except CorrectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except CorrectionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.get("", response_model=list[CorrectionResponse])
async def list_corrections(
    analysis_id: UUID = Query(description="Analysis whose corrections are listed."),
    limit: int = Query(default=50, ge=1, le=100),
    service: CorrectionService = Depends(get_correction_service),
    user: VerifiedUser = Depends(require_user),
) -> list[CorrectionResponse]:
    """List the caller's corrections for one of the caller's analyses."""
    try:
        corrections = await service.list_for_analysis(
            analysis_id,
            user_id=user.uid,
            limit=limit,
        )
    except CorrectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    return [serialize_correction(correction) for correction in corrections]


@router.get("/{correction_id}", response_model=CorrectionResponse)
async def get_correction(
    correction_id: UUID,
    service: CorrectionService = Depends(get_correction_service),
    user: VerifiedUser = Depends(require_user),
) -> CorrectionResponse:
    """Return one of the caller's own corrections; another user's is ``404``."""
    try:
        correction = await service.get(correction_id, user_id=user.uid)
    except CorrectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    return serialize_correction(correction)


@router.post("/{correction_id}/decision", response_model=CorrectionResponse)
async def decide_correction(
    correction_id: UUID,
    decision: CorrectionDecision,
    service: CorrectionService = Depends(get_correction_service),
    user: VerifiedUser = Depends(require_user),
) -> CorrectionResponse:
    """Approve or reject a pending correction.

    The transition is idempotent for the same status; changing an already
    decided correction is a ``409``. Approving never alters the analysis.
    """
    try:
        correction = await service.decide(
            correction_id,
            decision.status,
            user_id=user.uid,
        )
    except CorrectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except CorrectionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    logger.info(
        "correction decision id=%s status=%s",
        correction.id,
        correction.status,
    )
    return serialize_correction(correction)


@router.get("/{correction_id}/export")
async def export_correction(
    correction_id: UUID,
    fmt: Literal["corrected", "diff", "json"] = Query(
        default="corrected",
        alias="format",
    ),
    service: CorrectionService = Depends(get_correction_service),
    user: VerifiedUser = Depends(require_user),
) -> Response:
    """Download the corrected file, its diff, or its JSON representation."""
    try:
        content_type, filename, body = await service.export(
            correction_id,
            user_id=user.uid,
            fmt=fmt,
        )
    except CorrectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except CorrectionStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    return Response(
        content=body,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
