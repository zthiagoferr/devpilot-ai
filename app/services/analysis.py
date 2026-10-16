"""Application service for persisted analyses.

The service owns the read-only analysis flow: it validates the requested task,
enforces the configured source-code limit, runs the orchestration pipeline, and
persists a UI-ready normalized result. Development tasks are deliberately not
exposed here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.agents.orchestrator import OrchestratorAgent
from app.core.config import get_settings
from app.db.models import Analysis
from app.db.repositories import AnalysisRepository
from app.schemas.analysis import AnalysisCreate


# Public task name -> orchestrator task. ``code_analysis`` is the dashboard
# default and maps to the complete analysis pipeline so the consolidated
# ReportAgent result (code, tests, docs) is persisted.
_TASK_ALIASES: dict[str, str] = {
    "code_analysis": "full_analysis",
    "full_analysis": "full_analysis",
    "code": "code",
    "tests": "tests",
    "docs": "docs",
}


class InvalidAnalysisTaskError(ValueError):
    """Raised when the requested task is not a supported read-only analysis."""

    def __init__(self, task: str) -> None:
        self.task = task
        super().__init__(f"Unsupported analysis task: {task}")


class SourceCodeTooLargeError(ValueError):
    """Raised when the submitted source code exceeds the configured limit."""

    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(
            f"Source code is too large ({size} bytes); the limit is {limit} bytes."
        )


class AnalysisExecutionError(RuntimeError):
    """Raised when the orchestration pipeline cannot complete the analysis."""


class AnalysisService:
    """Coordinate analysis orchestration and persistence."""

    def __init__(
        self,
        repository: AnalysisRepository,
        orchestrator: OrchestratorAgent | None = None,
    ) -> None:
        self._repository = repository
        self._orchestrator = (
            orchestrator if orchestrator is not None else OrchestratorAgent()
        )

    async def create_analysis(
        self,
        request: AnalysisCreate,
        user_id: str | None = None,
    ) -> Analysis:
        """Run and persist one analysis request.

        ``user_id`` is the verified Firebase uid (or ``None`` for an anonymous
        submission) and is decided by the API layer, never by the client body.
        """
        task = str(request.task).strip()
        project_name = str(request.project_name).strip()
        source_code = request.source_code
        repository_url = (request.repository_url or "").strip() or None

        orchestrator_task = _TASK_ALIASES.get(task)
        if orchestrator_task is None:
            raise InvalidAnalysisTaskError(task)

        self._enforce_source_code_limit(source_code)

        orchestration = await self._orchestrator.execute(
            {
                "task": orchestrator_task,
                "project_name": project_name,
                "source_code": source_code,
            }
        )

        if orchestration.get("status") != "completed":
            raise AnalysisExecutionError(
                str(orchestration.get("message") or "Analysis could not be completed.")
            )

        result = self._normalize_result(orchestration)

        return await self._repository.create_analysis(
            task=task,
            project_name=project_name,
            source_code=source_code,
            result=result,
            status="completed",
            repository_url=repository_url,
            user_id=user_id,
        )

    async def list_analyses(
        self,
        limit: int = AnalysisRepository.DEFAULT_LIMIT,
        *,
        user_id: str,
    ) -> list[Analysis]:
        """Return the owner's persisted analyses, newest first."""
        return await self._repository.list_analyses(limit, user_id=user_id)

    async def get_analysis(
        self,
        analysis_id: UUID | str,
        *,
        user_id: str,
    ) -> Analysis | None:
        """Return one of the owner's analyses, or ``None`` when not visible."""
        try:
            identifier = (
                analysis_id
                if isinstance(analysis_id, UUID)
                else UUID(str(analysis_id))
            )
        except (TypeError, ValueError):
            return None
        return await self._repository.get_by_id(identifier, user_id=user_id)

    @staticmethod
    def _enforce_source_code_limit(source_code: str) -> None:
        limit = get_settings().max_source_code_bytes
        size = len(source_code.encode("utf-8"))
        if size > limit:
            raise SourceCodeTooLargeError(size, limit)

    @staticmethod
    def _normalize_result(orchestration: dict[str, Any]) -> dict[str, Any]:
        """Map an orchestration payload to the UI-facing result contract."""
        payload = orchestration.get("result")
        if not isinstance(payload, dict):
            payload = {}

        report = payload.get("report")
        insights = payload.get("insights")

        if isinstance(report, dict):
            issues = AnalysisService._flatten_issues(report.get("analyses"))
            score = report.get("overall_score", 0)
            summary = report.get("summary", "")
            normalized_report: dict[str, Any] = report
        else:
            issues = AnalysisService._as_issue_list(payload.get("issues"))
            score = payload.get("score", 0)
            summary = payload.get("summary", "")
            normalized_report = payload

        result: dict[str, Any] = {
            "score": AnalysisService._as_score(score),
            "summary": "" if summary is None else str(summary),
            "issues": issues,
            "report": normalized_report,
        }
        if insights is not None:
            result["insights"] = insights
        return result

    @staticmethod
    def _as_score(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _as_issue_list(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for issue in value:
            if isinstance(issue, dict):
                normalized.append(dict(issue))
            else:
                normalized.append({"message": str(issue)})
        return normalized

    @staticmethod
    def _flatten_issues(analyses: Any) -> list[dict[str, Any]]:
        if not isinstance(analyses, dict):
            return []
        issues: list[dict[str, Any]] = []
        # Several agents report the same blocking error (for example a syntax
        # error). Collapse identical findings so the UI does not repeat them.
        seen: set[tuple[str, str, str]] = set()
        for analysis in analyses.values():
            if not isinstance(analysis, dict):
                continue
            for issue in AnalysisService._as_issue_list(analysis.get("issues")):
                key = (
                    str(issue.get("severity")),
                    str(issue.get("message")),
                    str(issue.get("line")),
                )
                if key in seen:
                    continue
                seen.add(key)
                issues.append(issue)
        return issues
