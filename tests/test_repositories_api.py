"""API tests for repository discovery used by the dashboard.

The GitHub provider is real; only its HTTP transport is replaced with an
``httpx.MockTransport`` so the endpoint is validated without network access.
"""

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.github import get_github_provider, router as repositories_router
from app.integrations.github_httpx import GitHubHTTPXProvider


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/git/trees/main"):
        return httpx.Response(
            200,
            json={
                "truncated": False,
                "tree": [
                    {"type": "blob", "path": "src/app.py", "size": 120},
                    {"type": "blob", "path": "README.md", "size": 40},
                    {"type": "tree", "path": "src"},
                ],
            },
        )
    return httpx.Response(
        200,
        json={
            "name": "hello-world",
            "full_name": "octocat/hello-world",
            "default_branch": "main",
        },
    )


@pytest_asyncio.fixture
async def repository_app():
    app = FastAPI()
    app.include_router(repositories_router)

    async def override_provider():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as http:
            yield GitHubHTTPXProvider(http)

    app.dependency_overrides[get_github_provider] = override_provider

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield app, async_client


@pytest.mark.asyncio
async def test_load_repository_returns_files(repository_app) -> None:
    _, client = repository_app

    response = await client.post(
        "/repositories/load",
        json={"repository_url": "octocat/hello-world"},
    )

    assert response.status_code == 200
    paths = [item["path"] for item in response.json()["files"]]
    assert paths == ["src/app.py", "README.md"]


@pytest.mark.asyncio
async def test_load_repository_rejects_empty_reference(repository_app) -> None:
    _, client = repository_app

    response = await client.post("/repositories/load", json={"repository_url": ""})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_load_repository_translates_provider_errors(repository_app) -> None:
    app, client = repository_app

    async def failing_provider():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        ) as http:
            yield GitHubHTTPXProvider(http)

    app.dependency_overrides[get_github_provider] = failing_provider

    response = await client.post(
        "/repositories/load",
        json={"repository_url": "octocat/hello-world"},
    )

    assert response.status_code == 502
