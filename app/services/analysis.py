"""Application service for persisted analyses.

The service owns the domain contract for creating and reading analyses.  It
builds :class:`Analysis` entities and delegates storage to
:class:`AnalysisRepository`; it never touches the database session directly.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.models import Analysis
from app.db.repositories import AnalysisRepository


class AnalysisService:
    """Coordinate analysis persistence without accessing the database directly."""

    def __init__(self, repository: AnalysisRepository) -> None:
        self._repository = repository

    async def create_analysis(
        self,
        *,
        task: str,
        project_name: str,
        source_code: str,
        result: dict[str, Any] | list[Any] | None = None,
        status: str = "completed",
    ) -> Analysis:
        """Create and persist an analysis through the repository."""
        analysis = Analysis(
            task=task,
            project_name=project_name,
            source_code=source_code,
            result=result,
            status=status,
        )
        return await self._repository.create(analysis)

    async def get_analysis(self, analysis_id: UUID | str) -> Analysis | None:
        """Return an analysis by UUID, or ``None`` when it does not exist."""
        identifier = (
            analysis_id if isinstance(analysis_id, UUID) else UUID(str(analysis_id))
        )
        return await self._repository.get_by_id(identifier)

    async def list_analyses(self, limit: int = AnalysisRepository.DEFAULT_LIMIT) -> list[Analysis]:
        """Return persisted analyses, newest first."""
        return await self._repository.list(limit=limit)
