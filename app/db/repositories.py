"""Database repository for :class:`app.db.models.Analysis` records.

The repository is the only component that talks to the SQLAlchemy session for
analysis records.  It never commits or rolls back: transaction ownership stays
with the session lifecycle layer (``app.db.session``).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis


class AnalysisRepository:
    """Persistence operations for :class:`Analysis` records."""

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, analysis: Analysis) -> Analysis:
        """Persist a new analysis and return it with generated values loaded."""
        self.session.add(analysis)
        await self.session.flush()
        await self.session.refresh(analysis)
        return analysis

    async def get_by_id(self, analysis_id: UUID) -> Analysis | None:
        """Return an analysis by its identifier, or ``None`` when absent."""
        statement = select(Analysis).where(Analysis.id == analysis_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(self, limit: int = DEFAULT_LIMIT) -> list[Analysis]:
        """Return the newest analyses first, subject to a bounded limit."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer between 1 and 100")
        if not 1 <= limit <= self.MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {self.MAX_LIMIT}")

        statement = (
            select(Analysis)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
