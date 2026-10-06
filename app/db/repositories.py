"""Database repositories for analysis records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis


class AnalysisRepository:
    """Persistence operations for :class:`Analysis` records.

    The repository does not commit or roll back transactions. Transaction
    ownership remains with the session or application lifecycle layer.
    """

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_analysis(
        self,
        project_name: str,
        source_code: str,
        result: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Analysis:
        """Create, flush, and return an analysis record.

        Flushing makes generated ORM values available to the returned object
        without taking ownership of the surrounding transaction.
        """
        if result is None:
            result = kwargs.pop("results", None)
            if result is None:
                result = kwargs.pop("analysis_result", None)

        if kwargs:
            unexpected = next(iter(kwargs))
            raise TypeError(
                f"create_analysis() got an unexpected keyword argument "
                f"{unexpected!r}"
            )

        if result is None:
            raise TypeError("create_analysis() missing required argument: 'result'")

        analysis = Analysis(
            project_name=project_name,
            source_code=source_code,
            result=result,
        )
        self.session.add(analysis)
        await self.session.flush()
        await self.session.refresh(analysis)
        return analysis

    async def get_by_uuid(self, analysis_uuid: UUID) -> Analysis | None:
        """Return an analysis by its public UUID, if it exists."""
        statement = select(Analysis).where(Analysis.uuid == analysis_uuid)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_analyses(self, limit: int = DEFAULT_LIMIT) -> list[Analysis]:
        """Return the newest analyses first, subject to a bounded limit."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer between 1 and 100")
        if not 1 <= limit <= self.MAX_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {self.MAX_LIMIT}"
            )

        statement = (
            select(Analysis)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
