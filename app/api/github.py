"""Repository discovery API backed by the GitHub provider.

The dashboard loads the file tree of a public repository before choosing a file
to analyze.  The endpoint delegates to the injected
:class:`app.integrations.github_httpx.GitHubHTTPXProvider`, so provider errors
are translated into sanitized HTTP responses and no credentials leak.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.integrations.github_httpx import (
    GitHubHTTPXProvider,
    GitHubProviderError,
)


router = APIRouter(prefix="/repositories", tags=["repositories"])


class RepositoryLoadRequest(BaseModel):
    repository_url: str = Field(
        min_length=1,
        description="GitHub repository reference such as 'owner/name' or a GitHub URL.",
    )
    branch: str | None = Field(
        default=None,
        description="Optional branch; the repository default branch is used otherwise.",
    )


class RepositoryFileResponse(BaseModel):
    path: str
    size: int | None = None


class RepositoryLoadResponse(BaseModel):
    files: list[RepositoryFileResponse]


async def get_github_provider() -> AsyncIterator[GitHubHTTPXProvider]:
    """Build a GitHub provider with a request-scoped HTTP client."""
    settings = get_settings()
    token = (
        settings.github_token.get_secret_value()
        if settings.github_token is not None
        else None
    )
    async with httpx.AsyncClient() as client:
        yield GitHubHTTPXProvider(
            client,
            api_base_url=settings.github_api_base_url,
            token=token,
        )


@router.post("/load", response_model=RepositoryLoadResponse)
async def load_repository(
    request: RepositoryLoadRequest,
    provider: GitHubHTTPXProvider = Depends(get_github_provider),
) -> RepositoryLoadResponse:
    try:
        files = await provider.list_repository_files(
            request.repository_url,
            request.branch,
        )
    except GitHubProviderError:
        raise HTTPException(
            status_code=502,
            detail="The repository could not be loaded.",
        )

    return RepositoryLoadResponse(
        files=[RepositoryFileResponse(path=item.path, size=item.size) for item in files]
    )
