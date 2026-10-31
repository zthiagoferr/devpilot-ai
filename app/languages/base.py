"""Shared contracts for language detection and structural validation.

The language layer is deliberately independent from agents, services, and the
LLM. Validators only perform deterministic, static checks; they never execute
the analyzed source and never claim that a file compiles or runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast, runtime_checkable

#: Languages for which a validator is available. ``unknown`` is a detection
#: outcome, never a supported validation target.
SUPPORTED_LANGUAGES: tuple[str, ...] = (
    "python",
    "advpl",
    "html",
    "css",
    "javascript",
)

LanguageId = Literal["python", "advpl", "html", "css", "javascript", "unknown"]
LanguageSource = Literal["manual", "extension", "content", "fallback"]
Origin = Literal["validator", "ai", "mixed"]
AnalysisKind = Literal["heuristic_validation", "ia_analysis", "official_validation"]

#: Confidence of a validation *score*, which is deliberately distinct from the
#: detection confidence. A score of 100 means "no finding", not "no risk":
#:
#: * ``evaluated``   - the structural validator ran at high detection confidence;
#: * ``partial``     - a validator ran, but detection confidence is low enough
#:                     that the findings should be reviewed manually;
#: * ``skipped``     - no validator ran (unknown/undetected language), so the
#:                     neutral 100 is not an evaluation;
#: * ``unavailable`` - the validator raised, so the score reflects the error
#:                     warning rather than an analysis.
ScoreStatus = Literal["evaluated", "partial", "skipped", "unavailable"]

#: Stable, ordered vocabulary for :data:`ScoreStatus`.
SCORE_STATUSES: tuple[str, ...] = ("evaluated", "partial", "skipped", "unavailable")

#: Human-readable semantics of each :data:`ScoreStatus`, kept next to the type
#: so API, agents, and UI agree on what a score means.
SCORE_STATUS_MEANINGS: Mapping[str, str] = {
    "evaluated": "A structural validator ran with adequate detection confidence.",
    "partial": "A structural validator ran, but detection confidence was low.",
    "skipped": "No structural validator ran (language unknown or undetected).",
    "unavailable": "The structural validator could not complete.",
}

Severity = Literal[
    "critical",
    "high",
    "error",
    "medium",
    "warning",
    "low",
    "info",
]

#: Detection confidence at or above which a result is considered high
#: confidence.
AUTO_CONFIDENCE_THRESHOLD = 0.6

#: Lowest confidence that still selects a best candidate instead of falling
#: back to ``unknown``.
CANDIDATE_CONFIDENCE_FLOOR = 0.4

#: UI-facing severity vocabulary and the weight each value removes from the
#: 100-point score. ``error`` and ``warning`` are UI aliases of ``high`` and
#: ``medium``; :func:`normalize_severity` returns the canonical values.
SEVERITY_WEIGHT: dict[str, int] = {
    "critical": 50,
    "high": 25,
    "error": 25,
    "medium": 10,
    "warning": 10,
    "low": 3,
    "info": 0,
}

_SEVERITY_ALIASES: dict[str, str] = {
    "critical": "critical",
    "blocker": "critical",
    "fatal": "critical",
    "high": "high",
    "error": "high",
    "major": "high",
    "medium": "medium",
    "warning": "medium",
    "moderate": "medium",
    "low": "low",
    "minor": "low",
    "info": "info",
    "informational": "info",
    "suggestion": "info",
}


class UnsupportedLanguageError(ValueError):
    """Raised when a language has no registered validator."""

    def __init__(self, language: str) -> None:
        self.language = language
        super().__init__(f"Unsupported language: {language}")


def normalize_score_status(value: Any) -> ScoreStatus:
    """Return a valid :data:`ScoreStatus`, defaulting to ``evaluated``.

    The default keeps legacy payloads (which predate coverage metadata)
    compatible: a validator that ran is still considered an evaluation.
    """
    if isinstance(value, str) and value in SCORE_STATUSES:
        return cast(ScoreStatus, value)
    return "evaluated"


def normalize_severity(value: str | None) -> str:
    """Return the canonical severity for a UI or legacy severity value.

    Unknown values become ``info``. They are never promoted to an error, so a
    malformed provider payload cannot inflate the perceived severity.
    """
    if not isinstance(value, str):
        return "info"
    return _SEVERITY_ALIASES.get(value.strip().lower(), "info")


def compute_score(issues: Iterable[LanguageIssue]) -> int:
    """Return the 0-100 score implied by ``issues`` (never below zero)."""
    penalty = sum(
        SEVERITY_WEIGHT[normalize_severity(issue.severity)] for issue in issues
    )
    return max(0, 100 - penalty)


def copy_coverage(coverage: Mapping[str, Any]) -> dict[str, Any]:
    """Return an independent copy of a declared coverage mapping.

    Validators declare coverage once at module level, so a shallow ``dict()``
    would share the nested lists with the declaration. Copying them keeps a
    consumer from mutating the validator's own ``COVERAGE`` constant.
    """
    return {
        str(key): list(value) if isinstance(value, (list, tuple)) else value
        for key, value in coverage.items()
    }


@dataclass(frozen=True, slots=True)
class Detection:
    """Outcome of language detection.

    ``candidates`` contains ``(language, confidence)`` pairs ordered from the
    most to the least likely language. It is empty when detection fails.
    """

    language: LanguageId
    source: LanguageSource
    confidence: float
    reason: str
    candidates: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Optional repository context available to a validator.

    ``known_paths`` are POSIX paths relative to the repository root.
    ``tree_complete`` is ``False`` when the repository listing was truncated;
    reference checks then report ``unknown`` instead of ``missing``.
    """

    path: str | None = None
    known_paths: frozenset[str] = frozenset()
    tree_complete: bool = True
    truncated: bool = False
    apps_json_path: str | None = None
    protheus_version: str | None = None


@dataclass(frozen=True, slots=True)
class LanguageIssue:
    """One deterministic finding produced by a language validator."""

    severity: Severity
    message: str
    cause: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    language: str | None = None
    origin: Origin = "validator"
    analysis_kind: AnalysisKind = "heuristic_validation"
    code: str | None = None
    rule_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a stable, UI-serializable representation of the issue."""
        return {
            "severity": self.severity,
            "message": self.message,
            "cause": self.cause,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "language": self.language,
            "origin": self.origin,
            "analysis_kind": self.analysis_kind,
            "code": self.code,
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of validating one source file."""

    language: str
    detection: Detection
    issues: tuple[LanguageIssue, ...] = ()
    score: int = 100
    summary: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class LanguageValidator(Protocol):
    """Contract implemented by every deterministic language validator."""

    language: str

    def validate(
        self,
        source: str,
        context: ValidationContext,
    ) -> ValidationResult:
        """Analyze ``source`` without executing it."""
        ...
