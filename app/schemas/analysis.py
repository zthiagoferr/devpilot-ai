from typing import Any

from pydantic import BaseModel, Field


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