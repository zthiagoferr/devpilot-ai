"""Application service for persisted analyses."""

from __future__ import annotations

from datetime import datetime
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
        project_name: str,
        result: dict[str, Any],
        source_code: str | None = None,
    ) -> Analysis:
        """Create and persist an analysis through the repository."""
        values: dict[str, Any] = {
            "project_name": project_name,
            "result": result,
        }

        if source_code is not None:
            values["source_code"] = source_code

        analysis = Analysis(**values)
        return await self._repository.create(analysis)

    async def get_history(self) -> list[Analysis]:
        """Return all persisted analyses, newest first."""
        analyses = list(await self._repository.get_all())

        def created_at(analysis: Analysis) -> datetime:
            value = getattr(analysis, "created_at", None)
            if isinstance(value, datetime):
                return value
            return datetime.min

        analyses.sort(key=created_at, reverse=True)
        return analyses

    async def get_analysis(self, analysis_id: UUID | str) -> Analysis | None:
        """Return an analysis by UUID, or ``None`` when it does not exist."""
        identifier = (
            analysis_id
            if isinstance(analysis_id, UUID)
            else UUID(str(analysis_id))
        )
        return await self._repository.get_by_id(identifier)

    async def list_analyses(self) -> list[Analysis]:
        """Compatibility alias for retrieving analysis history."""
        return await self.get_history()

    async def get_analysis_by_id(
        self,
        analysis_id: UUID | str,
    ) -> Analysis | None:
        """Compatibility alias for UUID lookup."""
        return await self.get_analysis(analysis_id)
