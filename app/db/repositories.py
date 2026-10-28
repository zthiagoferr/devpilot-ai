"""Database repositories for analysis records and AI corrections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Analysis, AnalysisCorrection


def _require_owner(user_id: str | None) -> str:
    """Return the required owner identifier.

    Reads are owner-scoped by design. Requiring the identifier explicitly means
    a missing (or blank) ``user_id`` fails loudly instead of silently turning
    into an unscoped query that would expose every user's analyses.
    """
    owner = (user_id or "").strip()
    if not owner:
        raise ValueError("user_id is required to read analyses.")
    return owner


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
        *,
        task: str,
        project_name: str,
        source_code: str,
        result: dict[str, Any] | None = None,
        status: str = "completed",
        repository_url: str | None = None,
        user_id: str | None = None,
    ) -> Analysis:
        """Create, flush, and return an analysis record.

        ``user_id`` is ``None`` for an anonymous analysis; the value always
        comes from a verified token, never from the request body.

        Flushing makes generated ORM values available to the returned object
        without taking ownership of the surrounding transaction.
        """
        analysis = Analysis(
            task=task,
            project_name=project_name,
            source_code=source_code,
            result=result,
            status=status,
            repository_url=repository_url,
            user_id=user_id,
        )
        self.session.add(analysis)
        await self.session.flush()
        await self.session.refresh(analysis)
        return analysis

    async def get_by_id(
        self,
        analysis_id: UUID,
        *,
        user_id: str | None,
    ) -> Analysis | None:
        """Return an analysis owned by ``user_id``, or ``None``.

        A record owned by somebody else, or by nobody (a pre-existing
        anonymous row), is indistinguishable from a missing record so the
        caller can answer ``404`` without leaking its existence.
        """
        owner = _require_owner(user_id)
        statement = select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.user_id == owner,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_analyses(
        self,
        limit: int = DEFAULT_LIMIT,
        *,
        user_id: str | None,
    ) -> list[Analysis]:
        """Return the owner's newest analyses first, subject to a bounded limit."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer between 1 and 100")
        if not 1 <= limit <= self.MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {self.MAX_LIMIT}")

        owner = _require_owner(user_id)
        statement = (
            select(Analysis)
            .where(Analysis.user_id == owner)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())


class CorrectionAlreadyDecidedError(ValueError):
    """Raised when a decision tries to change an already decided correction."""


class CorrectionRepository:
    """Persistence operations for :class:`AnalysisCorrection` records.

    Like :class:`AnalysisRepository`, transaction ownership stays with the
    caller. Every read is owner-scoped: a correction owned by somebody else, or
    by nobody, is indistinguishable from a missing record.
    """

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 100

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **fields: Any) -> AnalysisCorrection:
        """Create, flush, and return a correction record."""
        correction = AnalysisCorrection(**fields)
        self.session.add(correction)
        await self.session.flush()
        await self.session.refresh(correction)
        return correction

    async def get_by_id(
        self,
        correction_id: UUID,
        *,
        user_id: str | None,
    ) -> AnalysisCorrection | None:
        """Return a correction owned by ``user_id``, or ``None``.

        A correction with ``user_id`` ``NULL`` is never returned: anonymous
        submissions remain unreadable by design (see the ADR).
        """
        owner = _require_owner(user_id)
        statement = select(AnalysisCorrection).where(
            AnalysisCorrection.id == correction_id,
            AnalysisCorrection.user_id == owner,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_analysis(
        self,
        analysis_id: UUID,
        *,
        user_id: str | None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[AnalysisCorrection]:
        """Return the owner's corrections for one analysis, newest first."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer between 1 and 100")
        if not 1 <= limit <= self.MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {self.MAX_LIMIT}")

        owner = _require_owner(user_id)
        statement = (
            select(AnalysisCorrection)
            .where(
                AnalysisCorrection.analysis_id == analysis_id,
                AnalysisCorrection.user_id == owner,
            )
            .order_by(AnalysisCorrection.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def decide(
        self,
        correction_id: UUID,
        status: str,
        *,
        user_id: str | None,
    ) -> AnalysisCorrection | None:
        """Record a decision on a pending correction.

        Returns ``None`` when the record is not visible to ``user_id``. The
        transition is idempotent for the same status and raises
        :class:`CorrectionAlreadyDecidedError` when it would change a decided
        record. Approving never mutates the related analysis.
        """
        correction = await self.get_by_id(correction_id, user_id=user_id)
        if correction is None:
            return None

        if correction.status == status:
            return correction
        if correction.status != "pending":
            raise CorrectionAlreadyDecidedError(
                "The correction has already been decided."
            )

        correction.status = status
        correction.decided_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(correction)
        return correction
