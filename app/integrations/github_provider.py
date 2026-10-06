"""Typed abstraction for accessing GitHub repositories.

The module intentionally defines only the provider contract. Concrete GitHub
clients should implement :class:`GitHubProvider`; the protocol itself must not
be instantiated.
"""

from dataclasses import dataclass
from typing import Protocol, TypeAlias


@dataclass(frozen=True, slots=True)
class RepositoryMetadata:
    """Metadata returned for a GitHub repository."""

    name: str
    full_name: str
    default_branch: str = "main"
    description: str | None = None
    owner: str | None = None
    html_url: str | None = None
    language: str | None = None
    stars: int = 0
    forks: int = 0


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    """A file discovered in a repository tree.

    ``path`` is relative to the repository root and uses POSIX separators.
    Recursive file discovery should return files at every directory depth and
    should not return directory entries.
    """

    path: str
    sha: str | None = None
    size: int | None = None
    html_url: str | None = None
    download_url: str | None = None


# Explicit GitHub-prefixed names are useful to callers that use several
# repository providers while the shorter names remain convenient defaults.
GitHubRepositoryMetadata: TypeAlias = RepositoryMetadata
GitHubRepositoryFile: TypeAlias = RepositoryFile


class GitHubProvider(Protocol):
    """Asynchronous contract for reading repository data from GitHub.

    ``repository`` is a provider-defined repository reference, commonly an
    ``owner/name`` string or a GitHub repository URL. Implementations must use
    the repository's actual default branch for default-branch lookups and must
    recursively discover repository files when implementing
    :meth:`list_repository_files`.
    """

    async def get_repository_metadata(
        self,
        repository: str,
    ) -> RepositoryMetadata:
        """Return metadata for ``repository``."""
        ...

    async def get_default_branch(
        self,
        repository: str,
    ) -> str:
        """Return the repository's default branch name."""
        ...

    async def list_repository_files(
        self,
        repository: str,
        branch: str | None = None,
    ) -> list[RepositoryFile]:
        """Recursively return repository files, optionally from ``branch``."""
        ...
