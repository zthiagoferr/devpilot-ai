"""Contracts for AI-proposed corrections.

The vocabulary is deliberately conservative: a correction is only ever
``pending``, ``approved``, or ``rejected``, and ``post_validation`` reports a
deterministic local re-validation, never an official build or execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.analysis import AnalysisIssue


class CorrectionIssueRef(BaseModel):
    """Heuristic issue a correction is expected to resolve."""

    message: str = Field(min_length=1, max_length=2000)
    severity: str = Field(default="info", max_length=20)
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    rule_id: str | None = Field(default=None, max_length=100)
    code: str | None = Field(default=None, max_length=100)


class CorrectionCreate(BaseModel):
    """Request body for one AI correction attempt."""

    analysis_id: UUID | None = None
    file: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=20)
    source_code: str = Field(min_length=1)
    issue: CorrectionIssueRef
    protheus_version: str | None = Field(default=None, max_length=50)


class PostValidationInfo(BaseModel):
    """Result of the deterministic, local re-validation of a correction."""

    status: Literal["passed", "failed", "not_run"] = "not_run"
    target_resolved: bool = False
    issues: list[AnalysisIssue] = Field(default_factory=list)
    summary: str = ""


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


class CorrectionDecision(BaseModel):
    """Approve or reject a pending correction."""

    status: Literal["approved", "rejected"]
