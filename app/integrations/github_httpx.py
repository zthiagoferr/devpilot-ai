"""Concrete asynchronous GitHub REST provider backed by httpx."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.integrations.github_provider import (
    GitHubProvider,
    RepositoryFile,
    RepositoryMetadata,
)


class GitHubProviderError(Exception):
    """Base class for safe GitHub provider errors."""


class GitHubRequestError(GitHubProviderError):
    """Raised when a request cannot be completed."""


class GitHubHTTPError(GitHubProviderError):
    """Raised when GitHub returns a non-success response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"GitHub returned HTTP status {status_code}.")


class GitHubResponseError(GitHubProviderError):
    """Raised when a GitHub response is malformed or incomplete."""


class GitHubTreeTruncatedError(GitHubProviderError):
    """Raised when GitHub cannot return the complete repository tree."""


@dataclass(frozen=True, slots=True)
class _RepositoryReference:
    owner: str
    name: str


class GitHubHTTPXProvider(GitHubProvider):
    """Read repository data from GitHub's REST API using an injected client.

    The client is deliberately required to be supplied by the caller. This
    keeps construction side-effect free and makes transport behavior easy to
    test without creating a client or making network requests implicitly.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_base_url: str = "https://api.github.com",
        token: str | None = None,
    ) -> None:
        if not isinstance(api_base_url, str) or not api_base_url.strip():
            raise ValueError("api_base_url must be a non-empty string.")
        if not hasattr(client, "get"):
            raise TypeError("client must provide an asynchronous get method.")

        self._client = client
        self._api_base_url = api_base_url.rstrip("/")
        self._token = token

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(api_base_url={self._api_base_url!r}, "
            "token_configured="
            f"{self._token is not None!r})"
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    def _reference(repository: str) -> _RepositoryReference:
        if not isinstance(repository, str) or not repository.strip():
            raise ValueError("repository must be a non-empty owner/name reference.")

        value = repository.strip()
        if "://" in value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
                "github.com",
                "www.github.com",
            }:
                raise ValueError("repository must be a GitHub owner/name reference.")
            value = parsed.path.strip("/")

        parts = [part for part in value.strip("/").split("/") if part]
        if len(parts) != 2:
            raise ValueError("repository must be a GitHub owner/name reference.")
        owner, name = parts
        if name.endswith(".git"):
            name = name[:-4]
        if not owner or not name:
            raise ValueError("repository must be a GitHub owner/name reference.")
        return _RepositoryReference(owner=owner, name=name)

    def _repository_url(self, repository: str) -> str:
        reference = self._reference(repository)
        owner = quote(reference.owner, safe="")
        name = quote(reference.name, safe="")
        return f"{self._api_base_url}/repos/{owner}/{name}"

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            response = await self._client.get(
                url,
                headers=self._headers(),
                params=params,
            )
        except Exception as exc:
            raise GitHubRequestError("GitHub request failed.") from None

        try:
            status_code = int(response.status_code)
        except Exception:
            raise GitHubRequestError("GitHub returned an invalid response.") from None
        if not 200 <= status_code < 300:
            raise GitHubHTTPError(status_code)

        try:
            payload = response.json()
        except Exception:
            raise GitHubResponseError("GitHub returned malformed JSON.") from None
        return payload

    @staticmethod
    def _required_string(payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise GitHubResponseError(
                f"GitHub response is missing a valid '{field}' field."
            )
        return value

    async def get_repository_metadata(self, repository: str) -> RepositoryMetadata:
        payload = await self._get_json(self._repository_url(repository))
        if not isinstance(payload, dict):
            raise GitHubResponseError("GitHub repository response must be an object.")

        name = self._required_string(payload, "name")
        full_name = self._required_string(payload, "full_name")
        default_branch = self._required_string(payload, "default_branch")

        owner_value = payload.get("owner")
        owner = None
        if owner_value is not None:
            if not isinstance(owner_value, dict) or not isinstance(
                owner_value.get("login"), str
            ):
                raise GitHubResponseError("GitHub repository owner is malformed.")
            owner = owner_value["login"]

        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise GitHubResponseError("GitHub repository description is malformed.")
        html_url = payload.get("html_url")
        language = payload.get("language")
        if html_url is not None and not isinstance(html_url, str):
            raise GitHubResponseError("GitHub repository URL is malformed.")
        if language is not None and not isinstance(language, str):
            raise GitHubResponseError("GitHub repository language is malformed.")

        stars = payload.get("stargazers_count", 0)
        forks = payload.get("forks_count", 0)
        if not isinstance(stars, int) or isinstance(stars, bool):
            raise GitHubResponseError("GitHub repository star count is malformed.")
        if not isinstance(forks, int) or isinstance(forks, bool):
            raise GitHubResponseError("GitHub repository fork count is malformed.")

        return RepositoryMetadata(
            name=name,
            full_name=full_name,
            default_branch=default_branch,
            description=description,
            owner=owner,
            html_url=html_url,
            language=language,
            stars=stars,
            forks=forks,
        )

    async def get_default_branch(self, repository: str) -> str:
        metadata = await self.get_repository_metadata(repository)
        return metadata.default_branch

    async def list_repository_files(
        self,
        repository: str,
        branch: str | None = None,
    ) -> list[RepositoryFile]:
        reference = self._reference(repository)
        selected_branch = branch if branch is not None else await self.get_default_branch(repository)
        if not isinstance(selected_branch, str) or not selected_branch:
            raise GitHubResponseError("A valid default branch was not provided.")

        tree_url = (
            f"{self._api_base_url}/repos/{quote(reference.owner, safe='')}"
            f"/{quote(reference.name, safe='')}/git/trees/"
            f"{quote(selected_branch, safe='')}"
        )
        payload = await self._get_json(tree_url, params={"recursive": "1"})
        if not isinstance(payload, dict):
            raise GitHubResponseError("GitHub tree response must be an object.")
        if payload.get("truncated") is True:
            raise GitHubTreeTruncatedError(
                "GitHub returned a truncated repository tree."
            )
        tree = payload.get("tree")
        if not isinstance(tree, list):
            raise GitHubResponseError("GitHub tree response is missing a valid 'tree' field.")

        files: list[RepositoryFile] = []
        for entry in tree:
            if not isinstance(entry, dict):
                raise GitHubResponseError("GitHub tree entry is malformed.")
            if entry.get("type") != "blob":
                continue
            path = self._required_string(entry, "path")
            sha = entry.get("sha")
            size = entry.get("size")
            html_url = entry.get("url")
            download_url = entry.get("download_url")
            if sha is not None and not isinstance(sha, str):
                raise GitHubResponseError("GitHub tree file SHA is malformed.")
            if size is not None and (not isinstance(size, int) or isinstance(size, bool)):
                raise GitHubResponseError("GitHub tree file size is malformed.")
            if html_url is not None and not isinstance(html_url, str):
                raise GitHubResponseError("GitHub tree file URL is malformed.")
            if download_url is not None and not isinstance(download_url, str):
                raise GitHubResponseError("GitHub tree download URL is malformed.")
            files.append(
                RepositoryFile(
                    path=path,
                    sha=sha,
                    size=size,
                    html_url=html_url,
                    download_url=download_url,
                )
            )
        return files


GitHubHttpxProvider = GitHubHTTPXProvider
