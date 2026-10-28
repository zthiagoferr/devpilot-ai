from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
)

from app.languages.base import SUPPORTED_LANGUAGES


def _validate_language(value: str | None) -> str | None:
    """Accept ``auto``/``None`` or a supported language; reject typos."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("language must be a string")
    normalized = value.strip().lower()
    if normalized in {"", "auto"}:
        return "auto"
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    raise ValueError(
        "language must be 'auto' or one of: "
        + ", ".join(SUPPORTED_LANGUAGES)
    )


class RepositoryContextFile(BaseModel):
    """One source file supplied as repository context for an analysis."""

    path: str = Field(min_length=1, max_length=500)
    source_code: str
    language: str | None = None


class RepositoryContext(BaseModel):
    """Optional repository context; relations never change score or issues."""

    files: list[RepositoryContextFile] = Field(default_factory=list)
    paths: list[str] | None = None
    tree_complete: bool = False
    truncated: bool = False
    apps_json: dict[str, Any] | None = None
    apps_json_path: str | None = None


class CodeAnalysisRequest(BaseModel):
    project_name: str = Field(
        min_length=1,
        description="Name of the project being analyzed.",
    )
    source_code: str = Field(
        min_length=1,
        description="Source code to analyze (language is detected automatically).",
    )
    language: str | None = Field(
        default="auto",
        description="Language override: 'auto' (default) or python/advpl/html/css/javascript.",
    )
    file_path: str | None = Field(
        default=None,
        description="Optional repository-relative file path used for detection and references.",
    )
    protheus_version: str | None = Field(
        default=None,
        description="Optional Protheus version used by the ADVPL validator.",
    )

    @field_validator("language")
    @classmethod
    def _check_language(cls, value: str | None) -> str | None:
        return _validate_language(value)


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
        description="Source code to analyze (language is detected automatically).",
    )
    # Optional repository origin persisted alongside the analysis. Extra fields
    # sent by the dashboard (``branch``) have no persistence column and are
    # ignored by Pydantic's default ``extra="ignore"`` policy.
    repository_url: str | None = None
    language: str | None = Field(
        default="auto",
        description="Language override: 'auto' (default) or python/advpl/html/css/javascript.",
    )
    file_path: str | None = Field(
        default=None,
        description="Optional repository-relative file path used for detection and references.",
    )
    protheus_version: str | None = None
    repository_context: RepositoryContext | None = None

    @field_validator("language")
    @classmethod
    def _check_language(cls, value: str | None) -> str | None:
        return _validate_language(value)


class AnalysisCreateRequest(AnalysisRequest):
    """Request body used to create and persist an analysis."""


class AnalysisIssue(BaseModel):
    severity: str
    message: str
    line: int | None = None
    cause: str | None = None
    file: str | None = None
    column: int | None = None
    language: str | None = None
    origin: str | None = None
    analysis_kind: str | None = None
    code: str | None = None
    rule_id: str | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> Any:
        """Keep the legacy issue shape while exposing the new fields.

        ``severity``/``message``/``line`` have always been part of the payload
        (including an explicit ``line: null``). The multi-language fields were
        added later, so a ``None`` value means "not applicable" and is omitted
        instead of changing the historical Python response shape.
        """
        data = handler(self)
        if isinstance(data, dict):
            for key in (
                "cause",
                "file",
                "column",
                "language",
                "origin",
                "analysis_kind",
                "code",
                "rule_id",
            ):
                if data.get(key) is None:
                    data.pop(key, None)
        return data


class CodeAnalysisResult(BaseModel):
    agent: str
    project_name: str
    score: int
    issues: list[AnalysisIssue]
    summary: str
    language: str = "python"
    language_source: str = "extension"
    confidence: float = 1.0
    corrections_available: bool = True


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
    repository_url: str | None = None
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
