"""Application service for persisted analyses.

The service owns the read-only analysis flow: it validates the requested task,
enforces the configured source-code limit, detects the source language, runs the
orchestration pipeline, and persists a UI-ready normalized result. Development
tasks are deliberately not exposed here.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.agents.orchestrator import OrchestratorAgent
from app.core.config import get_settings
from app.db.models import Analysis
from app.db.repositories import AnalysisRepository
from app.languages.base import ValidationContext
from app.languages.detector import detect_language
from app.schemas.analysis import AnalysisCreate, RepositoryContext
from app.services.relations import RepositorySource, build_repository_relations


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

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


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


class RepositoryContextTooLargeError(ValueError):
    """Raised when the repository context exceeds a configured limit."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class InvalidRepositoryContextError(ValueError):
    """Raised when a repository context path is unsafe or malformed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class AnalysisExecutionError(RuntimeError):
    """Raised when the orchestration pipeline cannot complete the analysis."""


@dataclass(frozen=True, slots=True)
class _PreparedRepositoryContext:
    """Normalized repository context ready for validation and relations."""

    paths: list[str] | None
    tree_complete: bool
    truncated: bool
    apps_json: dict[str, Any] | None
    apps_json_path: str | None
    sources: tuple[RepositorySource, ...]


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
        file_path = getattr(request, "file_path", None)
        language = getattr(request, "language", None)
        protheus_version = getattr(request, "protheus_version", None)
        repository_context = getattr(request, "repository_context", None)

        orchestrator_task = _TASK_ALIASES.get(task)
        if orchestrator_task is None:
            raise InvalidAnalysisTaskError(task)

        self._enforce_source_code_limit(source_code)

        prepared_context: _PreparedRepositoryContext | None = None
        if repository_context is not None:
            prepared_context = self._prepare_repository_context(repository_context)

        detection = detect_language(
            source_code,
            path=file_path,
            requested=language,
        )
        validation_context = self._build_validation_context(
            prepared_context,
            file_path=file_path,
            protheus_version=protheus_version,
        )

        orchestration = await self._orchestrator.execute(
            {
                "task": orchestrator_task,
                "project_name": project_name,
                "source_code": source_code,
                "language": language,
                "file_path": file_path,
                "detection": detection,
                "validation_context": validation_context,
                "protheus_version": protheus_version,
            }
        )

        if orchestration.get("status") != "completed":
            raise AnalysisExecutionError(
                str(orchestration.get("message") or "Analysis could not be completed.")
            )

        result = self._normalize_result(orchestration)
        result["language"] = detection.language
        result["language_source"] = detection.source
        result["confidence"] = round(float(detection.confidence), 2)

        if prepared_context is not None:
            relations = build_repository_relations(
                prepared_context.sources,
                known_paths=(
                    frozenset(prepared_context.paths)
                    if prepared_context.paths is not None
                    else None
                ),
                tree_complete=prepared_context.tree_complete,
                truncated=prepared_context.truncated,
                apps_json=prepared_context.apps_json,
                apps_json_path=prepared_context.apps_json_path,
                max_edges=int(
                    getattr(get_settings(), "relations_max_edges", 5000)
                ),
            )
            # Relations are metadata only: score and issues are untouched.
            result["relations"] = relations
            if isinstance(result.get("report"), dict):
                result["report"]["relations"] = relations

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
    def _normalize_repository_path(path: Any) -> str:
        """Return a safe repository-relative POSIX path or raise."""
        if not isinstance(path, str):
            raise InvalidRepositoryContextError(
                "Repository context paths must be strings."
            )
        value = path.strip().replace("\\", "/")
        if not value or "\x00" in value:
            raise InvalidRepositoryContextError(
                "Repository context paths must be non-empty and free of NUL bytes."
            )
        if value.startswith("/") or _WINDOWS_DRIVE_RE.match(value):
            raise InvalidRepositoryContextError(
                f"Repository context path must be relative: {path!r}."
            )
        normalized = posixpath.normpath(value)
        if (
            normalized in ("", ".")
            or normalized == ".."
            or normalized.startswith("../")
        ):
            raise InvalidRepositoryContextError(
                f"Repository context path escapes the repository root: {path!r}."
            )
        return normalized

    def _prepare_repository_context(
        self,
        context: RepositoryContext,
    ) -> _PreparedRepositoryContext:
        settings = get_settings()
        max_files = int(getattr(settings, "github_max_files", 1_000))
        max_file_bytes = int(getattr(settings, "github_max_file_bytes", 1_000_000))
        max_total_bytes = int(getattr(settings, "github_max_total_bytes", 5_000_000))

        if len(context.files) > max_files:
            raise RepositoryContextTooLargeError(
                f"Repository context has {len(context.files)} files; "
                f"the limit is {max_files}."
            )

        total_bytes = 0
        sources: list[RepositorySource] = []
        for item in context.files:
            path = self._normalize_repository_path(item.path)
            size = len(item.source_code.encode("utf-8"))
            if size > max_file_bytes:
                raise RepositoryContextTooLargeError(
                    f"Repository context file is too large ({size} bytes); "
                    f"the limit is {max_file_bytes} bytes."
                )
            total_bytes += size
            language = item.language
            if not isinstance(language, str) or not language.strip():
                language = detect_language(item.source_code, path=path).language
            else:
                language = language.strip().lower()
            sources.append(
                RepositorySource(
                    path=path,
                    source_code=item.source_code,
                    language=language,
                )
            )
        if total_bytes > max_total_bytes:
            raise RepositoryContextTooLargeError(
                f"Repository context is too large ({total_bytes} bytes); "
                f"the limit is {max_total_bytes} bytes."
            )

        paths: list[str] | None = None
        if context.paths is not None:
            # The path list is only reference metadata, but it is still bounded:
            # repositories may legitimately list more tree entries than are
            # supplied as file context, so the cap is twice the tree cap
            # (10_000 paths by default instead of 5_000).
            max_paths = int(getattr(settings, "github_max_tree_paths", 5_000)) * 2
            if len(context.paths) > max_paths:
                raise RepositoryContextTooLargeError(
                    f"Repository context has {len(context.paths)} paths; "
                    f"the limit is {max_paths}."
                )
            paths = [self._normalize_repository_path(path) for path in context.paths]

        apps_json_path = context.apps_json_path
        if apps_json_path is not None:
            apps_json_path = self._normalize_repository_path(apps_json_path)

        return _PreparedRepositoryContext(
            paths=paths,
            tree_complete=bool(context.tree_complete),
            truncated=bool(context.truncated),
            apps_json=context.apps_json,
            apps_json_path=apps_json_path,
            sources=tuple(sources),
        )

    @staticmethod
    def _build_validation_context(
        prepared: _PreparedRepositoryContext | None,
        *,
        file_path: str | None,
        protheus_version: str | None,
    ) -> ValidationContext:
        if prepared is None:
            return ValidationContext(
                path=file_path,
                protheus_version=protheus_version,
            )
        return ValidationContext(
            path=file_path,
            known_paths=frozenset(prepared.paths or []),
            tree_complete=prepared.tree_complete,
            truncated=prepared.truncated,
            apps_json_path=prepared.apps_json_path,
            protheus_version=protheus_version,
        )

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
        # ``file`` and ``language`` extend the key without changing the legacy
        # behavior when both are absent.
        seen: set[tuple[str, str, str, str, str]] = set()
        for analysis in analyses.values():
            if not isinstance(analysis, dict):
                continue
            for issue in AnalysisService._as_issue_list(analysis.get("issues")):
                key = (
                    str(issue.get("severity")),
                    str(issue.get("message")),
                    str(issue.get("line")),
                    str(issue.get("file") or ""),
                    str(issue.get("language") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                issues.append(issue)
        return issues
