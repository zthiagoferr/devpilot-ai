from typing import Any

import httpx
import pytest

from app.integrations.github_httpx import (
    GitHubHTTPError,
    GitHubHTTPXProvider,
    GitHubResponseError,
    GitHubTreeTruncatedError,
)


REPOSITORY = "octocat/hello-world"
TOKEN = "super-secret-token"


def make_provider(
    handler,
    *,
    token: str | None = None,
    api_base_url: str = "https://api.github.com",
):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubHTTPXProvider(
        client,
        token=token,
        api_base_url=api_base_url,
    )
    return provider, client


@pytest.mark.asyncio
async def test_public_metadata_request_omits_authorization() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "name": "hello-world",
                "full_name": REPOSITORY,
                "default_branch": "main",
            },
            request=request,
        )

    provider, client = make_provider(handler)
    try:
        metadata = await provider.get_repository_metadata(REPOSITORY)
    finally:
        await client.aclose()

    assert metadata.name == "hello-world"
    assert metadata.full_name == REPOSITORY
    assert metadata.default_branch == "main"
    assert "authorization" not in requests[0].headers
    assert requests[0].url.path == "/repos/octocat/hello-world"


@pytest.mark.asyncio
async def test_authenticated_request_sends_token_without_leaking_it() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "name": "hello-world",
                "full_name": REPOSITORY,
                "default_branch": "main",
            },
            request=request,
        )

    provider, client = make_provider(handler, token=TOKEN)
    try:
        await provider.get_repository_metadata(REPOSITORY)
    finally:
        await client.aclose()

    assert requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in repr(provider)


@pytest.mark.asyncio
async def test_metadata_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "name": "hello-world",
                "full_name": REPOSITORY,
                "default_branch": "develop",
                "description": "Example",
                "owner": {"login": "octocat"},
                "html_url": "https://github.com/octocat/hello-world",
                "language": "Python",
                "stargazers_count": 42,
                "forks_count": 7,
            },
            request=request,
        )

    provider, client = make_provider(handler)
    try:
        metadata = await provider.get_repository_metadata(REPOSITORY)
    finally:
        await client.aclose()

    assert metadata.name == "hello-world"
    assert metadata.default_branch == "develop"
    assert metadata.owner == "octocat"
    assert metadata.language == "Python"
    assert metadata.stars == 42
    assert metadata.forks == 7


@pytest.mark.asyncio
async def test_default_branch_drives_recursive_file_discovery() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)

        if request.url.path == "/repos/octocat/hello-world":
            return httpx.Response(
                200,
                json={
                    "name": "hello-world",
                    "full_name": REPOSITORY,
                    "default_branch": "develop",
                },
                request=request,
            )

        return httpx.Response(
            200,
            json={
                "tree": [
                    {"path": "src/main.py", "type": "blob", "sha": "a", "size": 10},
                    {"path": "src", "type": "tree"},
                    {"path": "README.md", "type": "blob", "sha": "b", "size": 20},
                ],
                "truncated": False,
            },
            request=request,
        )

    provider, client = make_provider(handler)
    try:
        files = await provider.list_repository_files(REPOSITORY)
    finally:
        await client.aclose()

    assert [file.path for file in files] == ["src/main.py", "README.md"]
    assert requests[-1].url.path.endswith("/git/trees/develop")
    assert requests[-1].url.params["recursive"] == "1"


@pytest.mark.asyncio
async def test_explicit_branch_avoids_metadata_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"tree": [], "truncated": False},
            request=request,
        )

    provider, client = make_provider(handler)
    try:
        files = await provider.list_repository_files(REPOSITORY, branch="feature")
    finally:
        await client.aclose()

    assert files == []
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/git/trees/feature")
    assert requests[0].url.params["recursive"] == "1"


@pytest.mark.asyncio
async def test_custom_api_base_url() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "name": "hello-world",
                "full_name": REPOSITORY,
                "default_branch": "main",
            },
            request=request,
        )

    provider, client = make_provider(
        handler,
        api_base_url="https://github.example.test/api/v3",
    )
    try:
        await provider.get_repository_metadata(REPOSITORY)
    finally:
        await client.aclose()

    assert requests[0].url.host == "github.example.test"
    assert requests[0].url.path == "/api/v3/repos/octocat/hello-world"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"tree": "not-a-list"},
        {"tree": [{"type": "blob"}]},
    ],
)
async def test_malformed_tree_responses_are_rejected(payload: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    provider, client = make_provider(handler)
    try:
        with pytest.raises(GitHubResponseError):
            await provider.list_repository_files(REPOSITORY, branch="main")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_malformed_json_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    provider, client = make_provider(handler)
    try:
        with pytest.raises(GitHubResponseError):
            await provider.get_repository_metadata(REPOSITORY)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_errors_are_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    provider, client = make_provider(handler)
    try:
        with pytest.raises(GitHubHTTPError) as caught:
            await provider.get_repository_metadata(REPOSITORY)
    finally:
        await client.aclose()

    assert caught.value.status_code == 503
    assert "503" in str(caught.value)


@pytest.mark.asyncio
async def test_truncated_tree_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"tree": [], "truncated": True},
            request=request,
        )

    provider, client = make_provider(handler)
    try:
        with pytest.raises(GitHubTreeTruncatedError):
            await provider.list_repository_files(REPOSITORY, branch="main")
    finally:
        await client.aclose()
