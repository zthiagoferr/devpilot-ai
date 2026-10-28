"""Turn a GitHub repository tree into analyzer-ready file contents.

The dashboard lets a user load a public repository and submits one of the
returned sources to the analysis pipeline. This module bridges the provider
(tree listing + Contents API) and that flow.

Scope decisions
---------------
* **Allowlist of supported languages.** The analysis pipeline has deterministic
  validators for Python, ADVPL, HTML5, CSS3, and JavaScript (see
  :mod:`app.languages`). Only the extensions of those languages are eligible;
  Markdown, JSON, or binary files are not downloaded because they cannot be
  analyzed meaningfully. A caller may narrow the allowlist with ``language``.
* **Truncation, not failure, for size limits.** Individual files above
  ``max_file_bytes`` are silently skipped (they cannot be analyzed anyway).
  Exceeding ``max_files`` or ``max_total_bytes`` stops the load and sets
  ``truncated=True`` instead of failing the whole request, so a user can still
  analyze the files that fit.
* **Repository paths for the relation graph.** Every blob path of the tree is
  collected (up to ``max_tree_paths``) so reference checks can distinguish
  ``resolved``/``missing`` from ``unknown``. When the path set is truncated the
  result reports ``tree_complete=False``.
* **Sequential content reads.** Files are fetched one at a time so the byte
  budget is enforced deterministically and the anonymous GitHub rate limit is
  not exhausted by a burst of parallel requests. Files whose content GitHub
  refuses to inline (binary, non-UTF-8, or larger than its inline limit) are
  skipped.
* **Per-file failures are skipped, not fatal.** A transient failure while
  reading one file (a 404 race between the tree listing and the content read, a
  403/429 rate limit, a 5xx, a timeout, or a malformed body) only removes that
  file from the result: the remaining files are still returned. Only when
  *every* download of the call fails transiently is a structured
  :class:`RepositoryDownloadUnavailableError` raised, so a rate limit is never
  reported as a missing repository.
* **Total time budget.** ``total_seconds`` bounds the whole load (branch
  resolution, tree listing, and every download share the same deadline). When
  the budget expires the load stops: if at least one file was already collected
  the result keeps those files with ``truncated=True``; otherwise
  :class:`RepositoryLoadDeadlineExceededError` is raised. ``None`` disables the
  budget.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from app.integrations.github_httpx import (
    GitHubContentUnavailableError,
    GitHubHTTPError,
    GitHubRequestError,
    GitHubResponseError,
)
from app.integrations.github_provider import GitHubProvider, RepositoryFile
from app.languages.base import SUPPORTED_LANGUAGES, UnsupportedLanguageError
from app.languages.detector import LANGUAGE_EXTENSIONS, detect_language


#: Extensions that a deterministic language validator can process meaningfully.
ELIGIBLE_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".pyi", ".prw", ".prg", ".ch", ".html", ".htm", ".css", ".js", ".mjs", ".cjs"}
)

#: Directories that never contain analyzer-ready source for this flow.
EXCLUDED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "site-packages",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "coverage",
    }
)

#: Path segments beginning with these prefixes are excluded (``.gitignore``,
#: ``.github/``, ``.env``, ``.env.local`` and similar).
EXCLUDED_SEGMENT_PREFIXES: tuple[str, ...] = (".git", ".env")


class RepositoryLoadError(Exception):
    """Base class for loader-level failures reported to the API layer."""


class RepositoryDownloadUnavailableError(RepositoryLoadError):
    """Raised when every eligible file download of a load failed transiently.

    ``status_code`` is the sanitized HTTP status that best describes the
    aggregate failure: ``429`` for rate limiting, ``504`` for timeouts, and
    ``502`` otherwise. It is never ``404``; a missing *file* must not be
    reported as a missing repository.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Repository file downloads failed with status {status_code}.")


class RepositoryLoadDeadlineExceededError(RepositoryLoadError):
    """Raised when the total load budget expires before any file is collected."""


#: Per-file failures that are skipped instead of aborting the whole load.
_TRANSIENT_FILE_ERRORS: tuple[type[Exception], ...] = (
    GitHubHTTPError,
    GitHubRequestError,
    GitHubResponseError,
)

_RATE_LIMIT_STATUS = 429
_GATEWAY_TIMEOUT_STATUS = 504
_BAD_GATEWAY_STATUS = 502

#: Lower rank wins when several transient failures must be aggregated.
_STATUS_PRIORITY: dict[int, int] = {
    _RATE_LIMIT_STATUS: 0,
    _GATEWAY_TIMEOUT_STATUS: 1,
    _BAD_GATEWAY_STATUS: 2,
}

_T = TypeVar("_T")


def _transient_status(error: Exception) -> int | None:
    """Return the sanitized status implied by a transient per-file failure.

    ``None`` means the failure is specific to a single file (a 404 race between
    the tree listing and the content read, for example) and must stay at file
    level: it is skipped and never surfaces as a repository-level 404.
    """
    if isinstance(error, GitHubHTTPError):
        status_code = error.status_code
        if status_code in (403, 429):
            return _RATE_LIMIT_STATUS
        if status_code == 408:
            return _GATEWAY_TIMEOUT_STATUS
        if status_code >= 500:
            return _BAD_GATEWAY_STATUS
        return None
    if isinstance(error, GitHubRequestError):
        return _GATEWAY_TIMEOUT_STATUS
    if isinstance(error, GitHubResponseError):
        return _BAD_GATEWAY_STATUS
    return None


def _deadline(total_seconds: float | None) -> float | None:
    """Return the monotonic instant at which the load must stop."""
    if total_seconds is None:
        return None
    return time.monotonic() + max(0.0, float(total_seconds))


async def _await_within_budget(
    factory: Callable[[], Awaitable[_T]],
    deadline: float | None,
) -> _T:
    """Await ``factory()`` within the remaining budget.

    A factory (instead of a coroutine) is required so that an already expired
    budget never creates a coroutine that would be left un-awaited.
    """
    if deadline is None:
        return await factory()

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RepositoryLoadDeadlineExceededError("The load budget is exhausted.")
    try:
        return await asyncio.wait_for(factory(), timeout=remaining)
    except asyncio.TimeoutError:
        raise RepositoryLoadDeadlineExceededError(
            "The load budget expired while waiting for GitHub."
        ) from None


@dataclass(frozen=True, slots=True)
class LoadedRepositoryFile:
    """A repository file whose decoded content is ready for analysis."""

    path: str
    size: int
    source_code: str
    language: str = "python"
    language_source: str = "extension"
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class RepositoryLoadResult:
    """Result of loading a repository for analysis."""

    files: list[LoadedRepositoryFile] = field(default_factory=list)
    truncated: bool = False
    #: Every blob path discovered in the tree, used by the relation graph.
    paths: list[str] = field(default_factory=list)
    #: ``False`` when the tree listing exceeded ``max_tree_paths``.
    tree_complete: bool = True
    apps_json: dict[str, object] | None = None
    apps_json_path: str | None = None


_AUTO_LANGUAGE_VALUES: frozenset[str] = frozenset({"", "auto", "none"})
_APPS_JSON_NAME = "apps.json"


def _language_extensions(language: str | None) -> frozenset[str] | None:
    """Return the eligible extensions of ``language`` (``None`` means all)."""
    if language is None:
        return None
    if not isinstance(language, str):
        raise UnsupportedLanguageError(str(language))
    normalized = language.strip().lower()
    if normalized in _AUTO_LANGUAGE_VALUES:
        return None
    if normalized not in SUPPORTED_LANGUAGES:
        raise UnsupportedLanguageError(language)
    return frozenset(
        extension
        for extension, mapped in LANGUAGE_EXTENSIONS.items()
        if mapped == normalized
    )


def _eligible_extension(path: str) -> str | None:
    segments = [segment for segment in path.strip().lstrip("/").split("/") if segment]
    if not segments:
        return None
    name = segments[-1]
    _, dot, extension = name.rpartition(".")
    if not dot or not extension:
        return None
    return f".{extension.lower()}"


def is_eligible_path(path: str) -> bool:
    """Return whether ``path`` may be downloaded for analysis."""
    if not isinstance(path, str):
        return False

    segments = [segment for segment in path.strip().lstrip("/").split("/") if segment]
    if not segments:
        return False

    for segment in segments:
        lowered = segment.lower()
        if lowered in EXCLUDED_DIRECTORIES:
            return False
        if lowered.startswith(EXCLUDED_SEGMENT_PREFIXES):
            return False

    extension = _eligible_extension(path)
    if extension is None:
        return False
    return extension in ELIGIBLE_EXTENSIONS


def _is_candidate(
    path: str,
    allowed_extensions: frozenset[str] | None,
) -> bool:
    if not is_eligible_path(path):
        return False
    if allowed_extensions is None:
        return True
    extension = _eligible_extension(path)
    return extension is not None and extension in allowed_extensions


def _select_candidates(
    entries: list[RepositoryFile],
    *,
    max_files: int,
    max_file_bytes: int,
    allowed_extensions: frozenset[str] | None = None,
) -> tuple[list[RepositoryFile], bool]:
    """Filter tree entries and cap the number of eligible files."""
    candidates: list[RepositoryFile] = []
    for entry in entries:
        if not _is_candidate(entry.path, allowed_extensions):
            continue
        if entry.size is not None:
            if isinstance(entry.size, bool) or entry.size <= 0:
                continue
            if entry.size > max_file_bytes:
                continue
        candidates.append(entry)

    if len(candidates) > max_files:
        return candidates[:max_files], True
    return candidates, False


def _collect_tree_paths(
    entries: list[RepositoryFile],
    max_tree_paths: int,
) -> tuple[list[str], bool]:
    """Return every blob path (deduplicated) and whether it is complete."""
    paths: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        path = entry.path
        if not isinstance(path, str) or not path.strip():
            continue
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    limit = max(0, int(max_tree_paths))
    if len(paths) > limit:
        return paths[:limit], False
    return paths, True


async def _read_apps_json(
    provider: GitHubProvider,
    repository: str,
    branch: str,
    *,
    deadline: float | None,
    max_bytes: int,
) -> dict[str, object] | None:
    """Read and parse the root ``apps.json`` metadata, ignoring any failure."""
    try:
        content = await _await_within_budget(
            lambda: provider.get_file_content(repository, _APPS_JSON_NAME, branch),
            deadline,
        )
    except Exception:  # noqa: BLE001 - metadata is best-effort
        return None
    if not isinstance(content, str):
        return None
    if len(content.encode("utf-8")) > max(0, int(max_bytes)):
        return None
    try:
        payload = json.loads(content)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


async def load_repository_files(
    provider: GitHubProvider,
    repository: str,
    branch: str | None = None,
    *,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
    total_seconds: float | None = None,
    language: str | None = None,
    max_tree_paths: int = 5_000,
    apps_json_max_bytes: int = 65_536,
) -> RepositoryLoadResult:
    """Load the analyzer-ready files of ``repository``.

    Repository-level provider errors (invalid reference, missing/private
    repository, truncated tree, repository-wide timeouts) propagate so the API
    layer can translate them into sanitized HTTP responses. Failures that are
    specific to one file are skipped; when every download fails transiently,
    :class:`RepositoryDownloadUnavailableError` is raised instead.

    ``total_seconds`` bounds the whole load; see the module docstring. A
    repository without eligible files is a successful (empty) result, never an
    error. Passing ``language`` narrows eligibility to that language's
    extensions.
    """
    allowed_extensions = _language_extensions(language)
    deadline = _deadline(total_seconds)

    if branch:
        selected_branch = branch
    else:
        selected_branch = await _await_within_budget(
            lambda: provider.get_default_branch(repository),
            deadline,
        )

    entries = await _await_within_budget(
        lambda: provider.list_repository_files(repository, selected_branch),
        deadline,
    )

    paths, tree_complete = _collect_tree_paths(entries, max_tree_paths)

    apps_json: dict[str, object] | None = None
    apps_json_path: str | None = None
    if _APPS_JSON_NAME in paths:
        apps_json_path = _APPS_JSON_NAME
        apps_json = await _read_apps_json(
            provider,
            repository,
            selected_branch,
            deadline=deadline,
            max_bytes=apps_json_max_bytes,
        )

    candidates, truncated = _select_candidates(
        entries,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        allowed_extensions=allowed_extensions,
    )


    files: list[LoadedRepositoryFile] = []
    total_bytes = 0
    download_attempts = 0
    transient_failures = 0
    aggregate_status: int | None = None

    for entry in candidates:
        download_attempts += 1
        try:
            content = await _await_within_budget(
                lambda path=entry.path: provider.get_file_content(
                    repository,
                    path,
                    selected_branch,
                ),
                deadline,
            )
        except GitHubContentUnavailableError:
            # Binary, non-UTF-8, or too large to inline: unusable by the analyzer.
            continue
        except RepositoryLoadDeadlineExceededError:
            if not files:
                raise
            # Keep what already fits; the caller can still analyze those files.
            truncated = True
            break
        except _TRANSIENT_FILE_ERRORS as error:
            status = _transient_status(error)
            if status is not None:
                transient_failures += 1
                if (
                    aggregate_status is None
                    or _STATUS_PRIORITY[status] < _STATUS_PRIORITY[aggregate_status]
                ):
                    aggregate_status = status
            continue

        encoded = content.encode("utf-8")
        if not encoded:
            continue
        if len(encoded) > max_file_bytes:
            continue
        if total_bytes + len(encoded) > max_total_bytes:
            truncated = True
            break

        total_bytes += len(encoded)
        detection = detect_language(content, path=entry.path)
        files.append(
            LoadedRepositoryFile(
                path=entry.path,
                size=len(encoded),
                source_code=content,
                language=detection.language,
                language_source=detection.source,
                confidence=round(float(detection.confidence), 2),
            )
        )

    if (
        not files
        and download_attempts
        and aggregate_status is not None
        and transient_failures == download_attempts
    ):
        # Every download failed transiently: report the aggregate cause instead
        # of pretending the repository (or an empty file list) is the answer.
        raise RepositoryDownloadUnavailableError(aggregate_status)

    return RepositoryLoadResult(
        files=files,
        truncated=truncated,
        paths=paths,
        tree_complete=tree_complete,
        apps_json=apps_json,
        apps_json_path=apps_json_path,
    )
