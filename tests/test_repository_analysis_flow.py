"""Integration test for the repository -> analysis flow with a real database.

This mirrors the dashboard's two-step workflow: load a public repository file
through ``POST /repositories/load`` and submit the returned ``source_code`` to
``POST /analyses``. The GitHub transport is mocked, but the HTTP stack, the
analysis service, and persistence are real.
"""

from __future__ import annotations

import base64

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db.models import Base
from app.integrations.github_httpx import GitHubHTTPXProvider

REPOSITORY = "octocat/hello-world"
REPOSITORY_URL = "https://github.com/octocat/hello-world"

# Real Python source with a genuine quality gap: a public function without a
# docstring. The full pipeline reports the missing docstring.
SOURCE = (
    "def compute_total(items):\n"
    "    total = 0\n"
    "    for item in items:\n"
    "        total += item\n"
    "    return total\n"
)


def _handler(request: httpx.Request) -> httpx.Response:
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
                    {"type": "blob", "path": "src/service.py", "size": len(SOURCE)},
                    {"type": "blob", "path": "README.md", "size": 10},
                ],
            },
            request=request,
        )
    if "/contents/" in path:
        relative = path.split("/contents/", 1)[1]
        if relative == "src/service.py":
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "encoding": "base64",
                    "size": len(SOURCE),
                    "path": relative,
                    "content": base64.b64encode(SOURCE.encode("utf-8")).decode("ascii"),
                },
                request=request,
            )
    return httpx.Response(404, request=request)


@pytest.fixture()
def repository_analysis_client(tmp_path, monkeypatch):
    """Return a ``TestClient`` with a real SQLite database and mocked GitHub."""
    from app.db import session as db_session

    db_path = tmp_path / "repository_flow.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    original_module_url = db_session.DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", database_url)
    db_session.DATABASE_URL = database_url
    db_session._engine = None
    db_session._session_factory = None

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    from app.api.deps import get_token_verifier
    from app.api.github import get_github_provider
    from app.main import app
    from tests.fake_auth import TEST_TOKEN, FakeTokenVerifier

    async def override_provider():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_handler)
        ) as http:
            yield GitHubHTTPXProvider(http)

    app.dependency_overrides[get_github_provider] = override_provider
    # The whole flow runs as one verified user so the analysis is owned and can
    # be read back through the owner-scoped history endpoints.
    app.dependency_overrides[get_token_verifier] = lambda: FakeTokenVerifier()

    try:
        with TestClient(
            app,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        ) as test_client:
            yield test_client, db_path
    finally:
        app.dependency_overrides.pop(get_github_provider, None)
        app.dependency_overrides.pop(get_token_verifier, None)
        db_session.DATABASE_URL = original_module_url
        db_session._engine = None
        db_session._session_factory = None


def test_repository_file_feeds_analysis_and_history(
    repository_analysis_client,
) -> None:
    client, _ = repository_analysis_client

    loaded = client.post(
        "/repositories/load",
        json={"repository_url": REPOSITORY},
    )
    assert loaded.status_code == 200, loaded.text
    files = loaded.json()["files"]
    assert [item["path"] for item in files] == ["src/service.py"]

    source_code = files[0]["source_code"]
    assert "def compute_total" in source_code

    created = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": REPOSITORY,
            "source_code": source_code,
            "repository_url": REPOSITORY_URL,
            "branch": "main",
            "file_path": "src/service.py",
        },
    )
    assert created.status_code == 201, created.text
    data = created.json()

    assert data["status"] == "completed"
    assert data["project_name"] == REPOSITORY
    assert data["source_code"] == source_code
    assert data["repository_url"] == REPOSITORY_URL
    assert data["result"]["score"] < 100
    messages = [issue.get("message", "") for issue in data["result"]["issues"]]
    assert any("docstring" in message for message in messages)

    listing = client.get("/analyses")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [data["id"]]
    assert listing.json()[0]["repository_url"] == REPOSITORY_URL

    detail = client.get(f"/analyses/{data['id']}")
    assert detail.status_code == 200
    assert detail.json()["source_code"] == source_code
    assert detail.json()["repository_url"] == REPOSITORY_URL
