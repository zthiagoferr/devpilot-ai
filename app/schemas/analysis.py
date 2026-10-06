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


class CodeIssue(BaseModel):
    severity: str
    message: str
    line: int | None = None


class CodeAnalysisResult(BaseModel):
    agent: str
    project_name: str
    score: int
    issues: list[CodeIssue]
    summary: str