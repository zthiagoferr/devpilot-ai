"""Contracts for AI-proposed corrections.

The vocabulary is deliberately conservative: a correction is only ever
``pending``, ``approved``, or ``rejected``, and ``post_validation`` reports a
deterministic local re-validation, never an official build or execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.repository_paths import (
    InvalidRepositoryPathError,
    normalize_repository_path,
)
from app.schemas.analysis import AnalysisIssue

#: A correction either targets one issue (``single``) or every listed issue in
#: the file (``full``). ``single`` is the default so existing clients keep
#: working without sending the field.
CorrectionMode = Literal["single", "full"]


class CorrectionIssueRef(BaseModel):
    """Heuristic issue a correction is expected to resolve."""

    message: str = Field(min_length=1, max_length=2000)
    severity: str = Field(default="info", max_length=20)
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    rule_id: str | None = Field(default=None, max_length=100)
    code: str | None = Field(default=None, max_length=100)
    cause: str | None = Field(default=None, max_length=100)


def _issue_signature(issue: CorrectionIssueRef) -> tuple[str, str, str, int | None]:
    """Return the deduplication identity of a correction target.

    ``rule_id``, ``cause``, and ``message`` are compared case-insensitively
    without surrounding/excess whitespace. The line keeps distinct occurrences
    of the same finding (two images without ``alt``) as separate targets.
    """
    return (
        " ".join((issue.rule_id or "").lower().split()),
        " ".join((issue.cause or "").lower().split()),
        " ".join((issue.message or "").lower().split()),
        issue.line,
    )


def _dedupe_issues(issues: list[CorrectionIssueRef]) -> list[CorrectionIssueRef]:
    """Drop duplicate targets while preserving the caller's order."""
    seen: set[tuple[str, str, str, int | None]] = set()
    unique: list[CorrectionIssueRef] = []
    for issue in issues:
        signature = _issue_signature(issue)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(issue)
    return unique


class CorrectionRepositoryContext(BaseModel):
    """Repository metadata used to re-run reference checks.

    Only the path tree is accepted: corrections never receive source files and
    never modify a repository. The list is bounded so a client cannot send an
    arbitrarily large tree.
    """

    paths: list[str] | None = Field(default=None, max_length=20_000)
    tree_complete: bool = False
    truncated: bool = False


class CorrectionCreate(BaseModel):
    """Request body for one AI correction attempt.

    ``mode='single'`` (the historical behaviour) requires exactly one ``issue``.
    ``mode='full'`` corrects every issue of the file in one pass: the caller may
    send ``issues`` explicitly, send a single ``issue`` (merged into the list
    for convenience), or send neither and let the backend derive the targets
    from the deterministic baseline validation. Repeated targets (same
    ``rule_id``/``cause``/``message`` and line) are removed before the request
    reaches the service so the same problem is never corrected twice.
    """

    analysis_id: UUID | None = None
    file: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=20)
    source_code: str = Field(min_length=1)
    mode: CorrectionMode = "single"
    issue: CorrectionIssueRef | None = None
    issues: list[CorrectionIssueRef] = Field(default_factory=list)
    protheus_version: str | None = Field(default=None, max_length=50)
    repository_context: CorrectionRepositoryContext | None = None

    @model_validator(mode="after")
    def _check_mode(self) -> "CorrectionCreate":
        if self.mode == "single":
            if self.issue is None:
                raise ValueError("issue is required when mode='single'")
            if self.issues:
                raise ValueError("issues is only accepted when mode='full'")
            return self

        # Full mode: ``issue`` is another target, not an alternative to
        # ``issues``. Both are merged (dropping exact duplicates) so a caller
        # that sends both never loses a problem silently. An empty list is
        # accepted on purpose: the backend derives the targets by running the
        # deterministic baseline validation.
        if self.issue is not None:
            self.issues = _dedupe_issues([*self.issues, self.issue])
        else:
            self.issues = _dedupe_issues(list(self.issues))
        return self


class CorrectionBatchFile(BaseModel):
    """One file of a batch correction request.

    The path is normalized to a repository-relative POSIX path at the contract
    boundary: an absolute path, a NUL byte, or any ``..`` segment is rejected
    with ``422`` before the service sees it. ``issues`` is optional: an empty
    list makes the backend derive the targets from the deterministic baseline
    of that file, exactly like the single-file ``full`` mode.
    """

    path: str = Field(min_length=1, max_length=500)
    source_code: str = Field(min_length=1)
    issues: list[CorrectionIssueRef] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        # A parent segment is rejected outright (even when it would normalize
        # back inside the repository) because a batch path must be literal.
        if ".." in value.replace("\\", "/").split("/"):
            raise ValueError("File paths must not contain '..' segments.")
        try:
            return normalize_repository_path(value)
        except InvalidRepositoryPathError as exc:
            raise ValueError(exc.reason) from None


#: Fixed schema cap for the batch payload. The parser materializes every
#: ``source_code`` before the service runs, so an unbounded list would let a
#: hostile client exhaust memory before the operational ``422``. This cap is
#: deliberately generous and static; the real, configurable limit stays in the
#: service (``correction_batch_max_files``, default 3).
MAX_BATCH_FILES = 25


class CorrectionBatchCreate(BaseModel):
    """Request body for a batch correction.

    ``files`` carries one entry per file; the batch-level ``language`` (when
    set) overrides detection for every file. ``repository_context`` is shared by
    all files so reference checks can tell a missing include from one outside
    the known tree.

    Duplicate paths are collapsed to their first occurrence at the contract
    boundary: the same file must never cost two provider calls. The fixed
    :data:`MAX_BATCH_FILES` cap protects the parser while the configurable
    service limit remains the source of truth for the operational maximum.
    """

    analysis_id: UUID | None = None
    files: list[CorrectionBatchFile] = Field(
        min_length=1,
        max_length=MAX_BATCH_FILES,
    )
    language: str | None = Field(default=None, max_length=20)
    protheus_version: str | None = Field(default=None, max_length=50)
    repository_context: CorrectionRepositoryContext | None = None

    @model_validator(mode="after")
    def _dedupe_files(self) -> "CorrectionBatchCreate":
        seen: set[str] = set()
        unique: list[CorrectionBatchFile] = []
        for file in self.files:
            if file.path in seen:
                continue
            seen.add(file.path)
            unique.append(file)
        self.files = unique
        return self


class PostValidationInfo(BaseModel):
    """Result of the deterministic, local re-validation of a correction.

    The first four fields keep the historical contract. The remaining ones are
    additive (empty defaults) so an older stored payload still serializes:
    ``issues_resolved``/``issues_remaining`` describe the original findings and
    ``issues_new``/``issues_warnings`` split the findings introduced by the
    correction into relevant (critical/high/medium) and low/info observations.
    An unverified TOTVS/Protheus identifier is a safety signal, so it is kept
    in ``issues_new`` even though its severity is low.
    """

    status: Literal["passed", "failed", "not_run"] = "not_run"
    target_resolved: bool = False
    issues: list[AnalysisIssue] = Field(default_factory=list)
    summary: str = ""
    issues_resolved: list[AnalysisIssue] = Field(default_factory=list)
    issues_remaining: list[AnalysisIssue] = Field(default_factory=list)
    issues_new: list[AnalysisIssue] = Field(default_factory=list)
    issues_warnings: list[AnalysisIssue] = Field(default_factory=list)


class CorrectionResponse(BaseModel):
    """Representation of a persisted correction."""

    id: UUID
    analysis_id: UUID | None = None
    language: str
    file: str | None = None
    issue_ref: str
    original_code: str
    corrected_code: str
    diff: str
    explanation: str
    origin: Literal["ai"] = "ai"
    post_validation: PostValidationInfo = Field(default_factory=PostValidationInfo)
    status: Literal["pending", "approved", "rejected"]
    model: str | None = None
    protheus_version: str | None = None
    created_at: datetime
    decided_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("post_validation", mode="before")
    @classmethod
    def _default_post_validation(cls, value: Any) -> Any:
        """Treat a missing stored payload as "not run" instead of failing."""
        if value is None:
            return PostValidationInfo()
        return value


class CorrectionBatchItem(BaseModel):
    """Outcome of one file inside a batch.

    A failed or skipped item never contains source code; only a bounded error
    code, an HTTP-classified status, and a sanitized detail. ``completed``
    items carry the persisted, still ``pending`` correction, so approval stays
    per file through the existing decision endpoint.
    """

    path: str
    status: Literal["completed", "failed", "skipped"]
    correction: CorrectionResponse | None = None
    issues_targeted: int = 0
    error_code: str | None = None
    error_status: int | None = None
    error_detail: str | None = None
    #: Machine-readable cause of a non-completed item (``no_issues``,
    #: ``budget``, ``sensitive_file``, ``not_utf8``, ...). ``error_code`` keeps
    #: the historical HTTP-oriented vocabulary; ``reason`` is the stable one a
    #: batch client uses to explain a skipped/failed file.
    reason: str | None = None


class CorrectionBatchResponse(BaseModel):
    """Aggregated result of a batch correction.

    A partial batch is normal: files already completed keep their persisted
    corrections even when a later file fails or the shared budget runs out.
    ``budget_exceeded`` distinguishes a time-budget skip from a per-file
    failure.
    """

    results: list[CorrectionBatchItem]
    files_total: int
    files_completed: int
    files_failed: int
    files_skipped: int
    issues_resolved_total: int = 0
    issues_remaining_total: int = 0
    issues_new_total: int = 0
    partial: bool = False
    budget_exceeded: bool = False


class CorrectionDecision(BaseModel):
    """Approve or reject a pending correction."""

    status: Literal["approved", "rejected"]
