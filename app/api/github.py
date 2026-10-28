"""Repository discovery API backed by the GitHub provider.

The dashboard loads the analyzable files of a public repository before choosing
one to analyze. The endpoint delegates to the injected
:class:`app.integrations.github_httpx.GitHubHTTPXProvider` and passes the tree
through :mod:`app.services.repository_loader`, so provider errors are
translated into sanitized HTTP responses and no credentials leak. The resulting
file contents also feed the deterministic relation graph.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings
from app.integrations.github_httpx import (
    GitHubHTTPError,
    GitHubHTTPXProvider,
    GitHubProviderError,
    GitHubRequestError,
    GitHubTreeTruncatedError,
)
from app.languages.base import SUPPORTED_LANGUAGES, UnsupportedLanguageError
from app.services.relations import RepositorySource, build_repository_relations
from app.services.repository_loader import (
    RepositoryDownloadUnavailableError,
    RepositoryLoadDeadlineExceededError,
    RepositoryLoadResult,
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
    language: str | None = Field(
        default="auto",
        description="Optional language filter: 'auto' or a supported language.",
    )

    @field_validator("language")
    @classmethod
    def _check_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized in {"", "auto"}:
            return "auto"
        if normalized in SUPPORTED_LANGUAGES:
            return normalized
        raise ValueError(
            "language must be 'auto' or one of: " + ", ".join(SUPPORTED_LANGUAGES)
        )


class RepositoryFileResponse(BaseModel):
    path: str
    size: int | None = None
    source_code: str | None = None
    language: str | None = None
    language_source: str | None = None
    confidence: float | None = None


class RepositoryLoadResponse(BaseModel):
    files: list[RepositoryFileResponse]
    truncated: bool = False
    paths: list[str] | None = None
    tree_complete: bool = False
    relations: dict[str, Any] | None = None
    protheus: dict[str, Any] | None = None
    message: str | None = Field(
        default=None,
        description=(
            "Set when the load succeeded but produced no analyzable file "
            "(for example a repository without supported sources)."
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


def _settings_value(settings: Any, name: str, default: Any) -> Any:
    """Read an optional setting without breaking older injected namespaces."""
    return getattr(settings, name, default)


def _build_relations(result: RepositoryLoadResult, max_edges: int) -> dict[str, Any]:
    sources = [
        RepositorySource(
            path=item.path,
            source_code=item.source_code,
            language=item.language,
        )
        for item in result.files
    ]
    return build_repository_relations(
        sources,
        known_paths=frozenset(result.paths) if result.paths else frozenset(),
        tree_complete=result.tree_complete,
        truncated=result.truncated,
        apps_json=result.apps_json,
        apps_json_path=result.apps_json_path,
        max_edges=max_edges,
    )


@router.post("/load", response_model=RepositoryLoadResponse)
async def load_repository(
    request: RepositoryLoadRequest,
    provider: GitHubHTTPXProvider = Depends(get_github_provider),
) -> RepositoryLoadResponse:
    """Load the analyzable files of a public repository.

    Response contract:

    * ``200`` with ``files`` non-empty: the analyzable sources, and
      ``truncated`` when a size/file-count limit or the total time budget cut
      the load short.
    * ``200`` with ``files: []``, ``truncated: false`` and ``message`` set: the
      repository is valid but has no eligible source file. An empty repository
      is intentionally **not** a 404.
    * ``404`` only when the repository itself is missing or not public
      (metadata/tree step); a per-file download failure never produces it.
    * ``422`` for an invalid reference, an unsupported language filter, or a
      tree GitHub could not enumerate, ``429`` for rate limiting, ``502``/``504``
      for upstream failures and budget exhaustion.
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
            language=request.language,
            max_tree_paths=_settings_value(settings, "github_max_tree_paths", 5_000),
            apps_json_max_bytes=_settings_value(
                settings, "github_apps_json_max_bytes", 65_536
            ),
        )
    except UnsupportedLanguageError:
        raise HTTPException(
            status_code=422,
            detail="The requested language is not supported.",
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
            language=item.language,
            language_source=item.language_source,
            confidence=item.confidence,
        )
        for item in result.files
    ]

    relations = _build_relations(
        result,
        int(_settings_value(settings, "relations_max_edges", 5_000)),
    )
    apps_json_metadata = relations.get("protheus", {}).get("apps_json")
    protheus = apps_json_metadata if result.apps_json_path is not None else None

    return RepositoryLoadResponse(
        files=files,
        truncated=result.truncated,
        paths=result.paths,
        tree_complete=result.tree_complete,
        relations=relations,
        protheus=protheus,
        message=(
            None
            if files
            else (
                "No eligible Python, ADVPL, HTML5, CSS3, or JavaScript files "
                "were found in this repository."
            )
        ),
    )
