"""Multi-language contracts for ``POST /repositories/load``."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.github import get_github_provider, router as repositories_router
from app.integrations.github_httpx import GitHubHTTPXProvider

REPOSITORY = "octocat/mixed-repo"

SOURCES = {
    "main.py": "def add(a, b):\n    return a + b\n",
    "app.js": "const value = ;\n",
    "index.html": (
        "<!doctype html>\n"
        '<html lang="en"><head><title>Mixed</title>'
        '<link rel="stylesheet" href="css/style.css">'
        '<script src="app.js"></script></head>'
        '<body><img src="missing.png">'
        '<img src="https://cdn.example/logo.png"></body></html>\n'
    ),
    "css/style.css": "body { background: url(../img/bg.png); }\n",
    "program.prw": '#Include "totvs.ch"\nUser Function X()\nReturn\n',
    "README.md": "# Mixed repository\n",
}

TREE_PATHS = [
    "main.py",
    "app.js",
    "index.html",
    "css/style.css",
    "program.prw",
    "img/bg.png",
    "README.md",
]


def _encode(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii") + "\n"


def _file_payload(path: str, source: str) -> dict[str, object]:
    return {
        "type": "file",
        "encoding": "base64",
        "size": len(source.encode("utf-8")),
        "path": path,
        "content": _encode(source),
    }


def _mixed_handler(paths: list[str] = TREE_PATHS):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPOSITORY}":
            return httpx.Response(
                200,
                json={
                    "name": "mixed-repo",
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
                        {"type": "blob", "path": item, "size": 512}
                        for item in paths
                    ],
                },
                request=request,
            )
        if "/contents/" in path:
            relative = path.split("/contents/", 1)[1]
            if relative in SOURCES:
                return httpx.Response(
                    200,
                    json=_file_payload(relative, SOURCES[relative]),
                    request=request,
                )
        return httpx.Response(404, request=request)

    return handler


def _make_app(handler) -> FastAPI:
    app = FastAPI()
    app.include_router(repositories_router)

    async def override_provider():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            yield GitHubHTTPXProvider(http)

    app.dependency_overrides[get_github_provider] = override_provider
    return app


async def _post_load(payload, *, handler=None) -> httpx.Response:
    transport = ASGITransport(app=_make_app(handler or _mixed_handler()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/repositories/load", json=payload)


@pytest.mark.asyncio
async def test_mixed_repository_returns_every_supported_language() -> None:
    response = await _post_load({"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    payload = response.json()

    languages = {item["path"]: item["language"] for item in payload["files"]}
    assert languages == {
        "main.py": "python",
        "app.js": "javascript",
        "index.html": "html",
        "css/style.css": "css",
        "program.prw": "advpl",
    }
    for item in payload["files"]:
        assert item["language_source"] == "extension"
        assert 0.0 < item["confidence"] <= 1.0
        assert item["source_code"] == SOURCES[item["path"]]

    assert payload["message"] is None
    assert payload["truncated"] is False
    assert payload["tree_complete"] is True
    assert payload["paths"] == TREE_PATHS


@pytest.mark.asyncio
async def test_empty_repository_message_cites_every_supported_language() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPOSITORY}":
            return httpx.Response(
                200,
                json={
                    "name": "mixed-repo",
                    "full_name": REPOSITORY,
                    "default_branch": "main",
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [{"type": "blob", "path": "README.md", "size": 10}],
            },
            request=request,
        )

    response = await _post_load({"repository_url": REPOSITORY}, handler=handler)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["files"] == []
    message = payload["message"]
    for language in ("Python", "ADVPL", "HTML5", "CSS3", "JavaScript"):
        assert language in message


@pytest.mark.asyncio
async def test_relations_are_returned_with_resolved_missing_and_external_edges() -> None:
    response = await _post_load({"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    relations = response.json()["relations"]

    assert relations["version"] == 1
    assert relations["generated_by"] == "deterministic"
    assert relations["tree_complete"] is True
    assert relations["truncated"] is False

    by_target = {
        edge["target"]: edge for edge in relations["edges"]
    }
    assert by_target["css/style.css"]["status"] == "resolved"
    assert by_target["app.js"]["status"] == "resolved"
    assert by_target["img/bg.png"]["status"] == "resolved"
    assert by_target["missing.png"]["status"] == "missing"
    assert by_target["https://cdn.example/logo.png"]["status"] == "external"
    assert by_target["totvs.ch"]["status"] == "external"

    assert relations["summary"] == {
        "resolved": 3,
        "missing": 1,
        "external": 2,
        "unknown": 0,
    }
    assert all(edge["line"] >= 1 for edge in relations["edges"])
    assert all(edge["column"] >= 1 for edge in relations["edges"])


@pytest.mark.asyncio
async def test_truncated_tree_reports_unknown_instead_of_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.github.get_settings",
        lambda: SimpleNamespace(
            github_max_files=1000,
            github_max_file_bytes=1_000_000,
            github_max_total_bytes=5_000_000,
            github_load_total_seconds=60.0,
            github_max_tree_paths=2,
            github_apps_json_max_bytes=65_536,
            relations_max_edges=5_000,
        ),
    )

    response = await _post_load({"repository_url": REPOSITORY})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["tree_complete"] is False
    assert payload["paths"] == ["main.py", "app.js"]

    summary = payload["relations"]["summary"]
    assert summary["missing"] == 0
    assert summary["unknown"] > 0
    # External references are still classified without the complete tree.
    assert summary["external"] > 0


@pytest.mark.asyncio
async def test_repository_language_filter_limits_the_downloaded_files() -> None:
    response = await _post_load(
        {"repository_url": REPOSITORY, "language": "advpl"}
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["path"] for item in payload["files"]] == ["program.prw"]
    # The tree paths are still complete, so relations can classify references.
    assert payload["paths"] == TREE_PATHS


@pytest.mark.asyncio
async def test_repository_rejects_unsupported_language_filter() -> None:
    response = await _post_load(
        {"repository_url": REPOSITORY, "language": "cobol"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_apps_json_metadata_is_exposed_in_the_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPOSITORY}":
            return httpx.Response(
                200,
                json={
                    "name": "mixed-repo",
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
                        {"type": "blob", "path": "apps.json", "size": 64},
                        {"type": "blob", "path": "main.py", "size": 32},
                    ],
                },
                request=request,
            )
        if "/contents/" in path:
            relative = path.split("/contents/", 1)[1]
            if relative == "apps.json":
                return httpx.Response(
                    200,
                    json=_file_payload(
                        "apps.json",
                        '{"applications": {"job": {}}}',
                    ),
                    request=request,
                )
            if relative == "main.py":
                return httpx.Response(
                    200,
                    json=_file_payload("main.py", SOURCES["main.py"]),
                    request=request,
                )
        return httpx.Response(404, request=request)

    response = await _post_load({"repository_url": REPOSITORY}, handler=handler)

    assert response.status_code == 200, response.text
    payload = response.json()
    apps_json = payload["protheus"]
    assert apps_json["path"] == "apps.json"
    assert apps_json["present"] is True
    assert apps_json["parsed"] is True
    assert apps_json["applications"] == 1
    assert apps_json["keys"] == ["applications"]
