"""Multi-language behaviour of :mod:`app.services.repository_loader`."""

from __future__ import annotations

import pytest

from app.integrations.github_provider import RepositoryFile
from app.languages.base import UnsupportedLanguageError
from app.services.repository_loader import is_eligible_path, load_repository_files
from tests.test_repository_loader import DEFAULT_LIMITS, FakeProvider


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "src/types.pyi",
        "src/program.prw",
        "src/legacy.prg",
        "include/totvs.ch",
        "index.html",
        "page.htm",
        "css/style.css",
        "js/app.js",
        "js/module.mjs",
        "js/config.cjs",
    ],
)
def test_new_language_extensions_are_eligible(path: str) -> None:
    assert is_eligible_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "dist/app.js",
        "build/app.py",
        "coverage/index.html",
        "src/dist/app.js",
        "README.md",
        "assets/logo.png",
        "data.json",
    ],
)
def test_generated_and_unsupported_directories_are_excluded(path: str) -> None:
    assert is_eligible_path(path) is False


@pytest.mark.asyncio
async def test_loader_collects_every_blob_path() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="src/app.py", size=10),
            RepositoryFile(path="README.md", size=20),
            RepositoryFile(path="js/app.js", size=20),
            RepositoryFile(path="node_modules/lib.js", size=20),
            RepositoryFile(path="assets/logo.png", size=20),
        ],
        {
            "src/app.py": "x = 1\n",
            "js/app.js": "const a = 1;\n",
        },
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert result.paths == [
        "src/app.py",
        "README.md",
        "js/app.js",
        "node_modules/lib.js",
        "assets/logo.png",
    ]
    assert result.tree_complete is True
    assert [item.path for item in result.files] == ["src/app.py", "js/app.js"]
    assert provider.content_calls == ["src/app.py", "js/app.js"]


@pytest.mark.asyncio
async def test_loader_marks_the_tree_incomplete_when_the_path_limit_is_hit() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="a.py", size=5),
            RepositoryFile(path="b.md", size=5),
            RepositoryFile(path="c.js", size=5),
        ],
        {"a.py": "a = 1\n", "c.js": "c = 3\n"},
    )

    result = await load_repository_files(
        provider,
        "octocat/hello-world",
        None,
        **DEFAULT_LIMITS,
        max_tree_paths=2,
    )

    assert result.paths == ["a.py", "b.md"]
    assert result.tree_complete is False
    assert [item.path for item in result.files] == ["a.py", "c.js"]


@pytest.mark.asyncio
async def test_loader_detects_and_parses_root_apps_json() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="apps.json", size=40),
            RepositoryFile(path="src/app.py", size=10),
        ],
        {
            "apps.json": '{"applications": {"job": {}, "report": {}}}',
            "src/app.py": "x = 1\n",
        },
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert result.apps_json_path == "apps.json"
    assert result.apps_json == {"applications": {"job": {}, "report": {}}}
    assert result.paths == ["apps.json", "src/app.py"]
    assert provider.content_calls == ["apps.json", "src/app.py"]


@pytest.mark.asyncio
async def test_loader_ignores_malformed_or_oversized_apps_json() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="apps.json", size=40),
            RepositoryFile(path="src/app.py", size=10),
        ],
        {"apps.json": "not-json", "src/app.py": "x = 1\n"},
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    assert result.apps_json_path == "apps.json"
    assert result.apps_json is None
    assert [item.path for item in result.files] == ["src/app.py"]

    oversized = await load_repository_files(
        provider,
        "octocat/hello-world",
        None,
        **DEFAULT_LIMITS,
        apps_json_max_bytes=4,
    )
    assert oversized.apps_json is None


@pytest.mark.asyncio
async def test_loader_filters_downloads_by_requested_language() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="app.py", size=10),
            RepositoryFile(path="app.js", size=20),
            RepositoryFile(path="index.html", size=30),
            RepositoryFile(path="style.css", size=30),
        ],
        {
            "app.py": "x = 1\n",
            "app.js": "const a = 1;\n",
            "index.html": "<html></html>",
            "style.css": "body { color: red; }",
        },
    )

    result = await load_repository_files(
        provider,
        "octocat/hello-world",
        None,
        **DEFAULT_LIMITS,
        language="javascript",
    )

    assert [item.path for item in result.files] == ["app.js"]
    assert provider.content_calls == ["app.js"]
    assert result.files[0].language == "javascript"


@pytest.mark.asyncio
async def test_loader_attaches_detected_language_metadata() -> None:
    provider = FakeProvider(
        [
            RepositoryFile(path="app.py", size=10),
            RepositoryFile(path="app.js", size=20),
            RepositoryFile(path="program.prw", size=20),
        ],
        {
            "app.py": "x = 1\n",
            "app.js": "const a = 1;\n",
            "program.prw": "User Function X()\nReturn\n",
        },
    )

    result = await load_repository_files(
        provider, "octocat/hello-world", None, **DEFAULT_LIMITS
    )

    by_path = {item.path: item for item in result.files}
    assert by_path["app.py"].language == "python"
    assert by_path["app.py"].language_source == "extension"
    assert by_path["app.py"].confidence == 0.99
    assert by_path["app.js"].language == "javascript"
    assert by_path["app.js"].confidence == 0.95
    assert by_path["program.prw"].language == "advpl"


@pytest.mark.asyncio
async def test_loader_rejects_an_unsupported_language_filter() -> None:
    provider = FakeProvider([], {})

    with pytest.raises(UnsupportedLanguageError):
        await load_repository_files(
            provider,
            "octocat/hello-world",
            None,
            **DEFAULT_LIMITS,
            language="cobol",
        )
