"""Pydantic schemas for analysis requests, results and persisted records.

The persisted record contract (:class:`AnalysisCreate` / :class:`AnalysisResponse`)
must mirror :class:`app.db.models.Analysis` exactly.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnalysisCreate(BaseModel):
    """Request body used to run and persist an analysis."""

    task: str = Field(
        min_length=1,
        max_length=100,
        description="Analysis task to run (for example 'code', 'tests', 'docs' or 'full_analysis').",
    )
    project_name: str = Field(
        min_length=1,
        max_length=255,
        description="Name of the project being analyzed.",
    )
    source_code: str = Field(
        min_length=1,
        description="Python source code to analyze.",
    )
    model_config = ConfigDict(extra="ignore")


class AnalysisResponse(BaseModel):
    """Representation of an analysis loaded from persistence."""

    id: UUID
    task: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    source_code: str = Field(min_length=1)
    result: dict[str, Any] | list[Any] | None = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Single-code-agent endpoints (app.api.agents) -------------------------


class CodeAnalysisRequest(BaseModel):
    project_name: str = Field(
        min_length=1,
        description="Name of the project being analyzed.",
    )
    source_code: str = Field(
        min_length=1,
        description="Python source code to analyze.",
    )


class AnalysisRequest(BaseModel):
    task: str = Field(
        min_length=1,
        description="Type of analysis that should be performed.",
    )
    project_name: str = Field(
        min_length=1,
        description="Name of the project being analyzed.",
    )
    source_code: str = Field(
        min_length=1,
        description="Python source code to analyze.",
    )


class AnalysisIssue(BaseModel):
    severity: str
    message: str
    line: int | None = None


class CodeAnalysisResult(BaseModel):
    agent: str
    project_name: str
    score: int
    issues: list[AnalysisIssue]
    summary: str


class OrchestratorStatus(BaseModel):
    agent: str
    responsibility: str
    status: str


class OrchestratorResponse(BaseModel):
    agent: str
    status: str
    delegated_to: str | list[str] | None = None
    result: dict[str, Any] | None = None
    message: str | None = None
