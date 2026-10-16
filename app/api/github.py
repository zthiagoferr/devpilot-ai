"""Repository discovery API backed by the GitHub provider.

The dashboard loads the Python files of a public repository before choosing one
to analyze.  The endpoint delegates to the injected
:class:`app.integrations.github_httpx.GitHubHTTPXProvider` and passes the tree
through :mod:`app.services.repository_loader`, so provider errors are
translated into sanitized HTTP responses and no credentials leak.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.integrations.github_httpx import (
    GitHubHTTPError,
    GitHubHTTPXProvider,
    GitHubProviderError,
    GitHubRequestError,
    GitHubTreeTruncatedError,
)
from app.services.repository_loader import (
    RepositoryDownloadUnavailableError,
    RepositoryLoadDeadlineExceededError,
    load_repository_files,
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
    source_code: str | None = None


class RepositoryLoadResponse(BaseModel):
    files: list[RepositoryFileResponse]
    truncated: bool = False
    message: str | None = Field(
        default=None,
        description=(
            "Set when the load succeeded but produced no analyzable file "
            "(for example a repository without Python sources)."
        ),
    )


async def get_github_provider() -> AsyncIterator[GitHubHTTPXProvider]:
    """Build a GitHub provider with a request-scoped HTTP client."""
    settings = get_settings()
    token = (
        settings.github_token.get_secret_value()
        if settings.github_token is not None
        else None
    )
    timeout = httpx.Timeout(15.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
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
    """Load the analyzable Python files of a public repository.

    Response contract:

    * ``200`` with ``files`` non-empty: the analyzable sources, and
      ``truncated`` when a size/file-count limit or the total time budget cut
      the load short.
    * ``200`` with ``files: []``, ``truncated: false`` and ``message`` set: the
      repository is valid but has no eligible Python file. An empty repository
      is intentionally **not** a 404.
    * ``404`` only when the repository itself is missing or not public
      (metadata/tree step); a per-file download failure never produces it.
    * ``422`` for an invalid reference or a tree GitHub could not enumerate,
      ``429`` for rate limiting, ``502``/``504`` for upstream failures and
      budget exhaustion.
    """
    settings = get_settings()

    try:
        result = await load_repository_files(
            provider,
            request.repository_url,
            request.branch,
            max_files=settings.github_max_files,
            max_file_bytes=settings.github_max_file_bytes,
            max_total_bytes=settings.github_max_total_bytes,
            total_seconds=settings.github_load_total_seconds,
        )
    except ValueError:
        # The provider rejects malformed ``owner/name`` references with ValueError.
        raise HTTPException(
            status_code=422,
            detail="The repository reference is not a valid GitHub owner/name.",
        )
    except GitHubTreeTruncatedError:
        raise HTTPException(
            status_code=422,
            detail="The repository is too large to enumerate completely.",
        )
    except GitHubRequestError:
        raise HTTPException(
            status_code=504,
            detail="The request to GitHub timed out or could not be completed.",
        )
    except GitHubHTTPError as exc:
        if exc.status_code in (403, 429):
            # GitHub reports rate limiting (and sometimes abuse detection) as
            # 403/429. Retrying after the reset window, or configuring a token,
            # resolves it.
            raise HTTPException(
                status_code=429,
                detail="The GitHub API rate limit was reached. Retry later.",
            )
        if exc.status_code in (401, 402, 404):
            # Nonexistent and private repositories are indistinguishable to an
            # unauthenticated caller; both are sanitized to 404.
            raise HTTPException(
                status_code=404,
                detail="The repository was not found or is not publicly accessible.",
            )
        raise HTTPException(
            status_code=502,
            detail="GitHub returned an unexpected response.",
        )
    except GitHubProviderError:
        raise HTTPException(
            status_code=502,
            detail="The repository could not be loaded.",
        )
    except RepositoryDownloadUnavailableError as exc:
        # Every eligible file failed transiently. The aggregate status is
        # sanitized by the loader and is never 404: a missing file must not be
        # reported as a missing repository.
        if exc.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="The GitHub API rate limit was reached. Retry later.",
            )
        if exc.status_code == 504:
            raise HTTPException(
                status_code=504,
                detail="The requests to GitHub timed out or could not be completed.",
            )
        raise HTTPException(
            status_code=502,
            detail="GitHub returned an unexpected response while reading files.",
        )
    except RepositoryLoadDeadlineExceededError:
        raise HTTPException(
            status_code=504,
            detail="Loading the repository exceeded the configured time budget.",
        )

    files = [
        RepositoryFileResponse(
            path=item.path,
            size=item.size,
            source_code=item.source_code,
        )
        for item in result.files
    ]

    return RepositoryLoadResponse(
        files=files,
        truncated=result.truncated,
        message=(
            None
            if files
            else "No eligible Python files were found in this repository."
        ),
    )
