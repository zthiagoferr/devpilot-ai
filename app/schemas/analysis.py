from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class AnalysisCreateRequest(AnalysisRequest):
    """Request body used to create and persist an analysis."""


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


class AnalysisResponse(BaseModel):
    """Representation of an analysis loaded from persistence."""

    id: UUID
    task: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    source_code: str = Field(min_length=1)
    result: dict[str, Any] | None = None
    status: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalysisHistoryQuery(BaseModel):
    """Parameters for retrieving a bounded page of analysis history."""

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of analyses to return.",
    )


AnalysisCreate = AnalysisCreateRequest
AnalysisRead = AnalysisResponse
PersistedAnalysisResponse = AnalysisResponse
AnalysisHistoryRequest = AnalysisHistoryQuery
AnalysisListQuery = AnalysisHistoryQuery
