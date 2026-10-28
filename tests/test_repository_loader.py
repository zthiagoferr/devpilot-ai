"""Unit tests for :mod:`app.services.repository_loader`.

A tiny in-memory provider keeps the tests focused on eligibility rules, limits,
and truncation semantics without any HTTP transport.
"""

from __future__ import annotations

import asyncio

import pytest

from app.integrations.github_httpx import (
    GitHubContentUnavailableError,
    GitHubHTTPError,
    GitHubRequestError,
)
from app.integrations.github_provider import RepositoryFile
from app.services.repository_loader import (
    RepositoryDownloadUnavailableError,
    RepositoryLoadDeadlineExceededError,
    is_eligible_path,
    load_repository_files,
)


class FakeProvider:
    """Minimal async provider used to drive the loader."""

    def __init__(
        self,
        files: list[RepositoryFile],
        contents: dict[str, str | Exception],
        *,
        default_branch: str = "main",
        delays: dict[str, float] | None = None,
    ) -> None:
        self._files = files
        self._contents = contents
        self._default_branch = default_branch
        self._delays = delays or {}
        self.branch_calls = 0
        self.content_calls: list[str] = []

    async def get_default_branch(self, repository: str) -> str:
        self.branch_calls += 1
        return self._default_branch

    async def get_repository_metadata(self, repository: str):  # pragma: no cover
        raise NotImplementedError

    async def list_repository_files(
        self,
        repository: str,
        branch: str | None = None,
    ) -> list[RepositoryFile]:
        return list(self._files)

    async def get_file_content(
        self,
        repository: str,
        path: str,
        branch: str | None = None,
    ) -> str:
        self.content_calls.append(path)
        delay = self._delays.get(path)
        if delay:
            await asyncio.sleep(delay)
        value = self._contents[path]
        if isinstance(value, Exception):
            raise value
        return value


DEFAULT_LIMITS = {
    "max_files": 1000,
    "max_file_bytes": 1_000_000,
    "max_total_bytes": 5_000_000,
}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app.py", True),
        ("service.PY", True),
        ("types.pyi", True),
        ("README.md", False),
        ("config.json", False),
        # Deliberate change: JavaScript is now an analyzable language.
        ("script.js", True),
        ("Makefile", False),
        ("src/.env", False),
        ("app/.env.local", False),
        (".env", False),
        (".gitignore", False),
        (".github/workflows/ci.yml", False),
        ("node_modules/pkg/index.py", False),
        ("src/__pycache__/app.cpython-312.pyc", False),
        ("", False),
        ("   ", False),
    ],
)
def test_is_eligible_path(path: str, expected: bool) -> None:
    assert is_eligible_path(path) is expected


@pytest.mark.asyncio
async def test_loader_filters_by_extension_exclusion_and_size() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="src/app.py", size=10),
            RepositoryFile(path="README.md", size=20),
            RepositoryFile(path=".env", size=5),
            RepositoryFile(path="node_modules/lib.py", size=5),
            RepositoryFile(path="tests/test_app.py", size=10),
            RepositoryFile(path="huge.py", size=2_000_000),
            RepositoryFile(path="empty.py", size=0),
        ],
        {
            "src/app.py": "x = 1\n",
            "tests/test_app.py": "def test_x():\n    assert True\n",
        },
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert [item.path for item in result.files] == ["src/app.py", "tests/test_app.py"]
    assert result.files[0].source_code == "x = 1\n"
    assert result.files[0].size == len("x = 1\n")
    assert result.truncated is False
    # Only eligible files are actually downloaded.
    assert provider.content_calls == ["src/app.py", "tests/test_app.py"]


@pytest.mark.asyncio
async def test_loader_truncates_at_max_files() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="a.py", size=5),
            RepositoryFile(path="b.py", size=5),
            RepositoryFile(path="c.py", size=5),
        ],
        {"a.py": "a = 1\n", "b.py": "b = 2\n", "c.py": "c = 3\n"},
    )

    result = await load_repository_files(
        provider,
        "octocat/hello-world",
        None,
        max_files=2,
        max_file_bytes=1_000_000,
        max_total_bytes=5_000_000,
    )

    assert [item.path for item in result.files] == ["a.py", "b.py"]
    assert result.truncated is True
    assert provider.content_calls == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_loader_truncates_when_total_bytes_exceeded() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="a.py", size=6),
            RepositoryFile(path="b.py", size=6),
            RepositoryFile(path="c.py", size=6),
        ],
        {"a.py": "a = 1\n", "b.py": "b = 2\n", "c.py": "c = 3\n"},
    )

    result = await load_repository_files(
        provider,
        "octocat/hello-world",
        None,
        max_files=100,
        max_file_bytes=1_000_000,
        max_total_bytes=10,
    )

    # "a = 1\n" is 6 bytes; the second file would push the total to 12 > 10.
    assert [item.path for item in result.files] == ["a.py"]
    assert result.truncated is True
    assert provider.content_calls == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_loader_skips_unavailable_content() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="binary.py", size=10),
            RepositoryFile(path="good.py", size=10),
        ],
        {
            "binary.py": GitHubContentUnavailableError("binary"),
            "good.py": "ok = True\n",
        },
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert [item.path for item in result.files] == ["good.py"]
    assert result.truncated is False


@pytest.mark.asyncio
async def test_loader_skips_empty_content() -> None:
    provider = FakeProvider(
        [RepositoryFile(path="blank.py", size=1)],
        {"blank.py": ""},
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert result.files == []


@pytest.mark.asyncio
async def test_loader_uses_explicit_branch_without_metadata_lookup() -> None:
    provider = FakeProvider(
        [RepositoryFile(path="a.py", size=5)],
        {"a.py": "a = 1\n"},
        default_branch="should-not-be-used",
    )

    await load_repository_files(
        provider, "octocat/hello-world", "feature", **DEFAULT_LIMITS
    )

    assert provider.branch_calls == 0


@pytest.mark.asyncio
async def test_loader_resolves_default_branch_when_missing_or_empty() -> None:
    for branch in (None, ""):
        provider = FakeProvider(
            [RepositoryFile(path="a.py", size=5)],
            {"a.py": "a = 1\n"},
        )

        await load_repository_files(provider, "octocat/hello-world", branch, **DEFAULT_LIMITS)

        assert provider.branch_calls == 1


@pytest.mark.asyncio
async def test_loader_skips_per_file_failures_and_keeps_the_other_files() -> None:
    """A single bad download (404 race, rate limit, 5xx, timeout) is not fatal."""
    provider = FakeProvider(
        [
            RepositoryFile(path="rate_limited.py", size=8),
            RepositoryFile(path="vanished.py", size=8),
            RepositoryFile(path="broken_upstream.py", size=8),
            RepositoryFile(path="slow.py", size=8),
            RepositoryFile(path="good.py", size=8),
        ],
        {
            "rate_limited.py": GitHubHTTPError(429),
            "vanished.py": GitHubHTTPError(404),
            "broken_upstream.py": GitHubHTTPError(503),
            "slow.py": GitHubRequestError("timed out"),
            "good.py": "ok = True\n",
        },
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert [item.path for item in result.files] == ["good.py"]
    assert result.truncated is False
    # Every candidate was attempted; only the healthy one was kept.
    assert provider.content_calls == [
        "rate_limited.py",
        "vanished.py",
        "broken_upstream.py",
        "slow.py",
        "good.py",
    ]


@pytest.mark.asyncio
async def test_loader_reports_rate_limit_when_every_download_is_rate_limited() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="a.py", size=5),
            RepositoryFile(path="b.py", size=5),
        ],
        {"a.py": GitHubHTTPError(429), "b.py": GitHubHTTPError(403)},
    )

    with pytest.raises(RepositoryDownloadUnavailableError) as caught:
        await load_repository_files(
            provider, "octocat/hello-world", None, **DEFAULT_LIMITS
        )

    # Rate limiting must stay a 429; it must never degrade into a 404.
    assert caught.value.status_code == 429


@pytest.mark.asyncio
async def test_loader_reports_timeout_when_every_download_times_out() -> None:
    provider = FakeProvider(
        [RepositoryFile(path="a.py", size=5)],
        {"a.py": GitHubRequestError("timed out")},
    )

    with pytest.raises(RepositoryDownloadUnavailableError) as caught:
        await load_repository_files(
            provider, "octocat/hello-world", None, **DEFAULT_LIMITS
        )

    assert caught.value.status_code == 504


@pytest.mark.asyncio
async def test_loader_returns_empty_result_when_every_file_is_missing() -> None:
    """Per-file 404s are a file-level problem: the repository is not missing."""
    provider = FakeProvider(
        [
            RepositoryFile(path="a.py", size=5),
            RepositoryFile(path="b.py", size=5),
        ],
        {"a.py": GitHubHTTPError(404), "b.py": GitHubHTTPError(404)},
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert result.files == []
    assert result.truncated is False


@pytest.mark.asyncio
async def test_loader_without_eligible_files_is_a_successful_empty_result() -> None:
    provider = FakeProvider(
        [RepositoryFile(path="README.md", size=50)],
        {},
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert result.files == []
    assert result.truncated is False
    assert provider.content_calls == []


@pytest.mark.asyncio
async def test_loader_returns_partial_result_when_total_budget_expires() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="a.py", size=6),
            RepositoryFile(path="b.py", size=6),
        ],
        {"a.py": "a = 1\n", "b.py": "b = 2\n"},
        delays={"b.py": 0.3},
    )

    result = await load_repository_files(
        provider,
        "octocat/hello-world",
        None,
        max_files=1000,
        max_file_bytes=1_000_000,
        max_total_bytes=5_000_000,
        total_seconds=0.05,
    )

    # The already collected file is kept and flagged as truncated.
    assert [item.path for item in result.files] == ["a.py"]
    assert result.truncated is True


@pytest.mark.asyncio
async def test_loader_raises_deadline_error_when_budget_expires_before_any_file() -> None:
    provider = FakeProvider(
        [RepositoryFile(path="a.py", size=6)],
        {"a.py": "a = 1\n"},
        delays={"a.py": 0.3},
    )

    with pytest.raises(RepositoryLoadDeadlineExceededError):
        await load_repository_files(
            provider,
            "octocat/hello-world",
            None,
            max_files=1000,
            max_file_bytes=1_000_000,
            max_total_bytes=5_000_000,
            total_seconds=0.05,
        )


@pytest.mark.asyncio
async def test_loader_expired_budget_stops_before_any_download() -> None:
    provider = FakeProvider(
        [RepositoryFile(path="a.py", size=6)],
        {"a.py": "a = 1\n"},
    )

    with pytest.raises(RepositoryLoadDeadlineExceededError):
        await load_repository_files(
            provider,
            "octocat/hello-world",
            "main",
            max_files=1000,
            max_file_bytes=1_000_000,
            max_total_bytes=5_000_000,
            total_seconds=0.0,
        )

    assert provider.content_calls == []
    assert provider.branch_calls == 0
