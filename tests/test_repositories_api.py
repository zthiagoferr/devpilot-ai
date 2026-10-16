"""API tests for repository discovery used by the dashboard.

The GitHub provider is real; only its HTTP transport is replaced with an
``httpx.MockTransport`` so the endpoint is validated without network access.
The backend now also downloads file contents through the GitHub Contents API,
so the mock transport serves both the tree and the per-file content payloads.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.github import get_github_provider, router as repositories_router
from app.integrations.github_httpx import GitHubHTTPXProvider


REPOSITORY = "octocat/hello-world"
PY_SOURCE = "def add(a, b):\n    return a + b\n"
TEST_SOURCE = "def test_add():\n    assert True\n"


def _encode(text: str) -> str:
    """Return GitHub's base64 body for ``text`` (with trailing newlines)."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii") + "\n"


def _file_payload(path: str, source: str) -> dict[str, object]:
    return {
        "type": "file",
        "encoding": "base64",
        "size": len(source.encode("utf-8")),
        "path": path,
        "content": _encode(source),
    }


def _success_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == f"/repos/{REPOSITORY}":
        return httpx.Response(
            200,
            json={
                "name": "hello-world",
                "full_name": REPOSITORY,
                "default_branch": "main",
            },
            request=request,
        )
    if path.endswith("/git/trees/main"):
        return httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"type": "blob", "path": "src/app.py", "size": len(PY_SOURCE)},
                    {"type": "blob", "path": "tests/test_app.py", "size": len(TEST_SOURCE)},
                    {"type": "blob", "path": "README.md", "size": 40},
                    {"type": "blob", "path": ".env", "size": 10},
                    {"type": "blob", "path": "node_modules/lib.py", "size": 10},
                    {"type": "blob", "path": "huge.py", "size": 5_000_000},
                    {"type": "tree", "path": "src"},
                ],
            },
            request=request,
        )
    if "/contents/" in path:
        relative = path.split("/contents/", 1)[1]
        if relative == "src/app.py":
            return httpx.Response(200, json=_file_payload(relative, PY_SOURCE), request=request)
        if relative == "tests/test_app.py":
            return httpx.Response(200, json=_file_payload(relative, TEST_SOURCE), request=request)
    return httpx.Response(404, request=request)


def _make_app(handler) -> FastAPI:
    app = FastAPI()
    app.include_router(repositories_router)

    async def override_provider():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield GitHubHTTPXProvider(http)

    app.dependency_overrides[get_github_provider] = override_provider
    return app


async def _post_load(handler, payload) -> httpx.Response:
    transport = ASGITransport(app=_make_app(handler))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/repositories/load", json=payload)


def _json_handler(status_code: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={}, request=request)

    return handler


def _tree_handler(*, truncated: bool) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/repos/{REPOSITORY}":
            return httpx.Response(
                200,
                json={
                    "name": "hello-world",
                    "full_name": REPOSITORY,
                    "default_branch": "main",
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"truncated": truncated, "tree": []},
            request=request,
        )

    return handler


def _repository_handler(paths: list[str], contents):
    """Serve metadata/tree for ``paths`` and delegate content responses.

    ``contents`` receives the repository-relative path and the request and must
    return an ``httpx.Response``, which lets each test inject per-file failures.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPOSITORY}":
            return httpx.Response(
                200,
                json={
                    "name": "hello-world",
                    "full_name": REPOSITORY,
                    "default_branch": "main",
                },
                request=request,
            )
        if path.endswith("/git/trees/main"):
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {"type": "blob", "path": item, "size": 64} for item in paths
                    ],
                },
                request=request,
            )
        if "/contents/" in path:
            return contents(path.split("/contents/", 1)[1], request)
        return httpx.Response(404, request=request)

    return handler


@pytest.mark.asyncio
async def test_load_repository_returns_files_with_source_code() -> None:
    response = await _post_load(_success_handler, {"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["truncated"] is False

    files = payload["files"]
    # Only eligible Python files survive; README.md, .env, node_modules and the
    # oversized file are filtered out.
    assert [item["path"] for item in files] == ["src/app.py", "tests/test_app.py"]
    assert files[0]["source_code"] == PY_SOURCE
    assert files[0]["size"] == len(PY_SOURCE.encode("utf-8"))
    assert files[1]["source_code"] == TEST_SOURCE


@pytest.mark.asyncio
async def test_load_repository_rejects_empty_reference() -> None:
    response = await _post_load(_success_handler, {"repository_url": ""})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_load_repository_rejects_invalid_reference() -> None:
    response = await _post_load(_success_handler, {"repository_url": "not-a-repository"})

    assert response.status_code == 422
    assert "owner/name" in response.json()["detail"]


@pytest.mark.asyncio
async def test_load_repository_reports_missing_repository_as_404() -> None:
    response = await _post_load(_json_handler(404), {"repository_url": REPOSITORY})

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_load_repository_maps_private_repository_402_to_404() -> None:
    response = await _post_load(_json_handler(402), {"repository_url": REPOSITORY})

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 429])
async def test_load_repository_reports_rate_limit(status_code: int) -> None:
    response = await _post_load(_json_handler(status_code), {"repository_url": REPOSITORY})

    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_load_repository_reports_truncated_tree() -> None:
    response = await _post_load(_tree_handler(truncated=True), {"repository_url": REPOSITORY})

    assert response.status_code == 422
    assert "too large" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_load_repository_reports_transport_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    response = await _post_load(handler, {"repository_url": REPOSITORY})

    assert response.status_code == 504


@pytest.mark.asyncio
async def test_load_repository_reports_unexpected_upstream_error() -> None:
    response = await _post_load(_json_handler(500), {"repository_url": REPOSITORY})

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_load_repository_truncates_at_configured_file_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.github.get_settings",
        lambda: SimpleNamespace(
            github_max_files=1,
            github_max_file_bytes=1_000_000,
            github_max_total_bytes=5_000_000,
            github_load_total_seconds=60.0,
        ),
    )

    response = await _post_load(_success_handler, {"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["truncated"] is True
    assert [item["path"] for item in payload["files"]] == ["src/app.py"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [404, 429, 500])
async def test_load_repository_skips_a_failing_file_and_returns_the_rest(
    status_code: int,
) -> None:
    """One failing download removes one file; the load is not aborted."""

    def contents(relative: str, request: httpx.Request) -> httpx.Response:
        if relative == "tests/test_app.py":
            return httpx.Response(status_code, json={}, request=request)
        return httpx.Response(200, json=_file_payload(relative, PY_SOURCE), request=request)

    handler = _repository_handler(["src/app.py", "tests/test_app.py"], contents)
    response = await _post_load(handler, {"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["path"] for item in payload["files"]] == ["src/app.py"]
    assert payload["truncated"] is False


@pytest.mark.asyncio
async def test_load_repository_reports_rate_limit_when_every_download_fails() -> None:
    """All downloads rate limited -> 429, never the misleading 404."""

    def contents(relative: str, request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={}, request=request)

    handler = _repository_handler(["src/app.py", "tests/test_app.py"], contents)
    response = await _post_load(handler, {"repository_url": REPOSITORY})

    assert response.status_code == 429, response.text
    assert "rate limit" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_load_repository_reports_timeout_when_every_download_times_out() -> None:
    def contents(relative: str, request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    handler = _repository_handler(["src/app.py"], contents)
    response = await _post_load(handler, {"repository_url": REPOSITORY})

    assert response.status_code == 504, response.text


@pytest.mark.asyncio
async def test_load_repository_does_not_report_missing_repository_for_missing_files() -> None:
    """Per-file 404s must not be sanitized into a repository-level 404."""

    def contents(relative: str, request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={}, request=request)

    handler = _repository_handler(["src/app.py"], contents)
    response = await _post_load(handler, {"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["files"] == []
    assert payload["truncated"] is False
    assert payload["message"]


@pytest.mark.asyncio
async def test_load_repository_returns_empty_contract_without_eligible_files() -> None:
    def contents(relative: str, request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no eligible file should be downloaded")

    handler = _repository_handler(["README.md", "node_modules/lib.py"], contents)
    response = await _post_load(handler, {"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["files"] == []
    assert payload["truncated"] is False
    assert payload["message"]


@pytest.mark.asyncio
async def test_load_repository_reports_total_budget_exhaustion(monkeypatch) -> None:
    """The configured total budget is applied to the whole load."""
    monkeypatch.setattr(
        "app.api.github.get_settings",
        lambda: SimpleNamespace(
            github_max_files=1000,
            github_max_file_bytes=1_000_000,
            github_max_total_bytes=5_000_000,
            github_load_total_seconds=0.0,
        ),
    )

    response = await _post_load(_success_handler, {"repository_url": REPOSITORY})

    assert response.status_code == 504, response.text
    assert "budget" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_load_repository_does_not_leak_token(monkeypatch) -> None:
    secret = "ghp_super_secret_value_123"
    monkeypatch.setenv("GITHUB_TOKEN", secret)

    response = await _post_load(_success_handler, {"repository_url": REPOSITORY})

    assert response.status_code == 200
    assert secret not in response.text
