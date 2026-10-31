"""Language-aware analysis agents.

These agents sit between the deterministic language validators
(:mod:`app.languages`) and the orchestration/report contracts. They never parse
Python with :mod:`ast`: every finding comes from the validator registered for
the detected language, so a JavaScript or ADVPL source is never treated as
Python.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.languages.base import (
    Detection,
    ValidationContext,
    copy_coverage,
    normalize_score_status,
)
from app.languages.detector import detect_language
from app.languages.registry import validate_source

_REPORT_ANALYSIS_FIELDS: tuple[str, ...] = (
    "agent",
    "score",
    "issues",
    "summary",
    "language",
    "validation_skipped",
)


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _detection_for(context: dict[str, Any]) -> Detection:
    """Return the context detection, computing it when absent."""
    detection = context.get("detection")
    if isinstance(detection, Detection):
        return detection
    return detect_language(
        _as_text(context.get("source_code")),
        path=context.get("file_path") or context.get("path"),
        requested=context.get("language") or context.get("requested_language"),
    )


def _validation_context(context: dict[str, Any]) -> ValidationContext:
    supplied = context.get("validation_context")
    if isinstance(supplied, ValidationContext):
        return supplied
    return ValidationContext(
        path=context.get("file_path") or context.get("path"),
        protheus_version=context.get("protheus_version"),
    )


def _requested_language(
    context: dict[str, Any],
    detection: Detection,
) -> str | None:
    """Choose the manual override passed to the validator registry.

    A caller-supplied manual ``Detection`` (without an explicit ``language``)
    must still drive the validator; otherwise the source would be re-detected
    and could select a different language.
    """
    requested = context.get("language") or context.get("requested_language")
    if requested is None or (isinstance(requested, str) and not requested.strip()):
        if detection.source == "manual":
            return detection.language
    return requested


def detection_as_dict(detection: Detection) -> dict[str, Any]:
    """Return a JSON-serializable representation of ``detection``."""
    return {
        "language": detection.language,
        "source": detection.source,
        "confidence": round(float(detection.confidence), 2),
        "reason": detection.reason,
        "candidates": [
            [language, round(float(confidence), 2)]
            for language, confidence in detection.candidates
        ],
    }


def _coverage_entry(analysis: dict[str, Any]) -> dict[str, Any]:
    """Return the per-language coverage block exposed by the report.

    The per-analysis keys are a fixed contract (see
    ``tests/test_language_agent.py``), so coverage lives at the report top level
    keyed by language instead of changing ``analyses[language]``.
    """
    coverage = analysis.get("coverage")
    checks = coverage.get("checks") if isinstance(coverage, dict) else None
    limitations = coverage.get("limitations") if isinstance(coverage, dict) else None
    return {
        "score_status": normalize_score_status(analysis.get("score_status")),
        "checks": (
            [str(item) for item in checks]
            if isinstance(checks, (list, tuple))
            else []
        ),
        "limitations": (
            [str(item) for item in limitations]
            if isinstance(limitations, (list, tuple))
            else []
        ),
    }


class LanguageCodeAgent(BaseAgent):
    """Validate non-Python source with the deterministic language validator."""

    def __init__(self) -> None:
        super().__init__(
            name="language_agent",
            responsibility=(
                "Validate non-Python source with its deterministic language "
                "validator."
            ),
        )

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        detection = _detection_for(context)
        validation_context = _validation_context(context)
        source_code = _as_text(context.get("source_code"))

        result = validate_source(
            source_code,
            requested_language=_requested_language(context, detection),
            path=validation_context.path,
            context=validation_context,
        )

        validator = result.metadata.get("validator")
        coverage = result.metadata.get("coverage")
        payload: dict[str, Any] = {
            "agent": self.name,
            "project_name": str(context.get("project_name") or ""),
            "score": int(result.score),
            "score_status": normalize_score_status(
                result.metadata.get("score_status")
            ),
            "issues": [issue.as_dict() for issue in result.issues],
            "summary": str(result.summary or ""),
            "language": result.language,
            "language_source": result.detection.source,
            "confidence": round(float(result.detection.confidence), 2),
            "validator": validator if isinstance(validator, dict) else None,
            "coverage": (
                copy_coverage(coverage) if isinstance(coverage, dict) else None
            ),
            "validation_skipped": bool(
                result.metadata.get("validation_skipped", False)
            ),
        }
        requested_task = context.get("requested_task")
        if isinstance(requested_task, str) and requested_task:
            payload["requested_task"] = requested_task
        return payload


class LanguageReportAgent(BaseAgent):
    """Consolidate a language validation into the ReportAgent payload shape."""

    def __init__(self, code_agent: LanguageCodeAgent | None = None) -> None:
        super().__init__(
            name="language_report_agent",
            responsibility=(
                "Consolidate deterministic language validation results into a "
                "report."
            ),
        )
        self._code_agent = code_agent if code_agent is not None else LanguageCodeAgent()

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        detection = _detection_for(context)
        analysis = await self._code_agent.execute({**context, "detection": detection})

        analyses = {
            analysis["language"]: {
                field: analysis[field] for field in _REPORT_ANALYSIS_FIELDS
            }
        }
        total_issues = len(analysis["issues"])
        overall_score = int(analysis["score"])
        requested_task = context.get("requested_task")
        if not isinstance(requested_task, str) or not requested_task:
            requested_task = "full_analysis"

        return {
            "agent": self.name,
            "project_name": str(context.get("project_name") or ""),
            "overall_score": overall_score,
            "total_issues": total_issues,
            "analyses": analyses,
            "coverage": {
                analysis["language"]: _coverage_entry(analysis),
            },
            "summary": (
                f"Analysis completed with an overall score of "
                f"{overall_score}/100 and {total_issues} issue(s) found."
            ),
            "language": detection_as_dict(detection),
            "requested_task": requested_task,
        }


__all__ = [
    "LanguageCodeAgent",
    "LanguageReportAgent",
    "detection_as_dict",
]
