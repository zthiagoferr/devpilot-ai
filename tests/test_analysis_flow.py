"""End-to-end tests for persisted ``/analyses`` using a real database.

Unlike ``tests/test_api.py`` (which overrides the service with a fake) these
tests exercise the real ``AnalysisService`` and ``AnalysisRepository`` against a
temporary SQLite database, so wiring defects cannot stay masked.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Base

# Valid Python code with a real quality gap: a public function without a
# docstring and no accompanying tests. The full analysis pipeline reports both.
SAMPLE_SOURCE = (
    "def compute_total(items):\n"
    "    total = 0\n"
    "    for item in items:\n"
    "        total += item\n"
    "    return total\n"
)

BROKEN_SOURCE = "def compute_total(items)\n    return sum(items)\n"


@pytest.fixture()
def analysis_client(tmp_path, monkeypatch):
    """Return a ``TestClient`` backed by a fresh real SQLite database."""
    from app.db import session as db_session

    db_path = tmp_path / "analyses.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    original_module_url = db_session.DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", database_url)
    db_session.DATABASE_URL = database_url
    db_session._engine = None
    db_session._session_factory = None

    # Create the schema with a synchronous engine that writes the same file.
    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    from app.main import app

    try:
        with TestClient(app) as test_client:
            yield test_client, db_path
    finally:
        db_session.DATABASE_URL = original_module_url
        db_session._engine = None
        db_session._session_factory = None


def _assert_normalized_result(result: dict) -> None:
    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert isinstance(result["summary"], str)
    assert isinstance(result["issues"], list)
    assert isinstance(result["report"], dict)


def test_create_analysis_persists_and_normalizes_result(analysis_client) -> None:
    client, db_path = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "sample-project",
            "source_code": SAMPLE_SOURCE,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["task"] == "code_analysis"
    assert data["project_name"] == "sample-project"
    assert data["source_code"] == SAMPLE_SOURCE
    assert data["status"] == "completed"
    assert data["repository_url"] is None
    assert data["created_at"]
    _assert_normalized_result(data["result"])
    assert data["result"]["score"] < 100

    # The consolidated ReportAgent output is embedded in the persisted result.
    report = data["result"]["report"]
    assert report["agent"] == "report_agent"
    assert "overall_score" in report
    assert "analyses" in report

    # The docs warning about the missing docstring is surfaced in ``issues``.
    messages = [issue.get("message", "") for issue in data["result"]["issues"]]
    assert any("docstring" in message for message in messages)

    analysis_id = data["id"]

    # The record is physically present in SQLite with the requested task.
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT task, project_name, status FROM analyses WHERE id = ?",
            (analysis_id.replace("-", ""),),
        ).fetchone()
    finally:
        connection.close()
    assert row == ("code_analysis", "sample-project", "completed")

    # History lists the record and the detail endpoint returns it.
    listing = client.get("/analyses")
    assert listing.status_code == 200
    ids = [item["id"] for item in listing.json()]
    assert ids == [analysis_id]
    _assert_normalized_result(listing.json()[0]["result"])

    detail = client.get(f"/analyses/{analysis_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == analysis_id
    assert detail.json()["project_name"] == "sample-project"


def test_create_analysis_persists_repository_url_and_ignores_extra_fields(
    analysis_client,
) -> None:
    client, db_path = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "repo-project",
            "source_code": SAMPLE_SOURCE,
            "repository_url": "https://github.com/example/repo",
            # Fields the dashboard may send without a persistence column.
            "branch": "main",
            "file_path": "example.py",
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["repository_url"] == "https://github.com/example/repo"

    analysis_id = data["id"]
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT repository_url FROM analyses WHERE id = ?",
            (analysis_id.replace("-", ""),),
        ).fetchone()
    finally:
        connection.close()
    assert row == ("https://github.com/example/repo",)

    listing = client.get("/analyses")
    assert listing.status_code == 200
    assert listing.json()[0]["repository_url"] == "https://github.com/example/repo"


def test_create_analysis_reports_syntax_error_as_completed(analysis_client) -> None:
    client, _ = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "broken-project",
            "source_code": BROKEN_SOURCE,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["status"] == "completed"
    assert data["result"]["score"] == 0
    assert data["result"]["issues"]
    assert any(
        issue.get("severity") == "critical"
        for issue in data["result"]["issues"]
    )

    # The same blocking syntax error is reported by several agents and must be
    # collapsed into a single finding.
    keys = [
        (issue.get("severity"), issue.get("message"), issue.get("line"))
        for issue in data["result"]["issues"]
    ]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("task", ["code_analysis", "full_analysis", "code", "tests", "docs"])
def test_create_analysis_accepts_supported_tasks(analysis_client, task) -> None:
    client, _ = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": task,
            "project_name": "task-project",
            "source_code": SAMPLE_SOURCE,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["task"] == task
    assert data["status"] == "completed"
    _assert_normalized_result(data["result"])


def test_create_analysis_rejects_unknown_and_development_tasks(
    analysis_client,
) -> None:
    client, _ = analysis_client

    for task in ("security", "develop", "multi_file_develop", "autonomous_develop"):
        response = client.post(
            "/analyses",
            json={
                "task": task,
                "project_name": "sample-project",
                "source_code": SAMPLE_SOURCE,
            },
        )
        assert response.status_code == 400, task
        assert response.json()["detail"] == f"Unsupported analysis task: {task}"


def test_create_analysis_rejects_empty_input(analysis_client) -> None:
    client, _ = analysis_client

    for payload in (
        {"task": "", "project_name": "demo", "source_code": SAMPLE_SOURCE},
        {"task": "code_analysis", "project_name": "", "source_code": SAMPLE_SOURCE},
        {"task": "code_analysis", "project_name": "demo", "source_code": ""},
        {"task": "code_analysis", "project_name": "demo"},
    ):
        response = client.post("/analyses", json=payload)
        assert response.status_code == 422, payload


def test_create_analysis_rejects_oversized_source_code(
    analysis_client,
    monkeypatch,
) -> None:
    from app.services import analysis as analysis_service

    client, _ = analysis_client
    monkeypatch.setattr(
        analysis_service,
        "get_settings",
        lambda: SimpleNamespace(max_source_code_bytes=10),
    )

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "too-big",
            "source_code": "x" * 32,
        },
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


def test_list_analyses_on_empty_history(analysis_client) -> None:
    client, _ = analysis_client

    response = client.get("/analyses")

    assert response.status_code == 200
    assert response.json() == []


def test_get_analysis_with_unknown_id_returns_404(analysis_client) -> None:
    client, _ = analysis_client

    response = client.get(f"/analyses/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Analysis not found"


@pytest.mark.asyncio
async def test_repository_round_trip_with_real_session(tmp_path) -> None:
    from app.db.repositories import AnalysisRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'repo.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with factory() as session:
            repository = AnalysisRepository(session)
            created = await repository.create_analysis(
                task="code_analysis",
                project_name="repo-project",
                source_code="print('hello')\n",
                result={"score": 42, "summary": "ok", "issues": [], "report": {}},
            )
            await session.commit()

            assert created.id is not None

            fetched = await repository.get_by_id(created.id)
            assert fetched is not None
            assert fetched.project_name == "repo-project"
            assert fetched.result["score"] == 42

            listed = await repository.list_analyses(limit=10)
            assert [record.id for record in listed] == [created.id]
    finally:
        await engine.dispose()


def test_create_analysis_without_llm_api_key_returns_real_ast_result(
    analysis_client,
    monkeypatch,
) -> None:
    """The AST analysis flow must work without any LLM key configured.

    With a fake/absent provider and no key, startup must not fail and the
    persisted result must contain the real deterministic AST findings, without
    any LLM-fabricated insights.
    """
    from app.core.config import Settings, get_settings

    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()

    try:
        settings = Settings()
        assert settings.llm_provider == "fake"
        assert not (
            settings.llm_api_key and settings.llm_api_key.get_secret_value()
        )

        client, _ = analysis_client
        response = client.post(
            "/analyses",
            json={
                "task": "code_analysis",
                "project_name": "no-llm-project",
                "source_code": SAMPLE_SOURCE,
            },
        )

        assert response.status_code == 201, response.text
        result = response.json()["result"]

        # Real, deterministic analysis: a score, a summary and issues.
        assert isinstance(result["score"], int)
        assert result["score"] < 100
        assert isinstance(result["summary"], str)
        assert result["issues"]
        # No LLM configured means no fabricated insights.
        assert "insights" not in result
    finally:
        get_settings.cache_clear()
