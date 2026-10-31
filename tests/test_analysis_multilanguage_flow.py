"""End-to-end multi-language analysis flow tests (real database wiring)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db.models import Base


@pytest.fixture()
def analysis_client(tmp_path, monkeypatch):
    """Return a ``TestClient`` backed by a fresh real SQLite database."""
    from app.db import session as db_session

    db_path = tmp_path / "multilanguage.db"
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
    from app.main import app
    from tests.fake_auth import TEST_TOKEN, FakeTokenVerifier

    app.dependency_overrides[get_token_verifier] = lambda: FakeTokenVerifier()

    try:
        with TestClient(
            app,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        ) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_token_verifier, None)
        db_session.DATABASE_URL = original_module_url
        db_session._engine = None
        db_session._session_factory = None


def test_agents_code_javascript_issue_has_structural_fields() -> None:
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/agents/code",
        json={
            "project_name": "mixed",
            "source_code": "const value = ;\n",
            "file_path": "app.js",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["agent"] == "language_agent"
    assert data["language"] == "javascript"
    assert data["language_source"] == "extension"
    assert data["confidence"] == 0.95
    assert data["corrections_available"] is True
    assert data["score_status"] == "evaluated"
    assert "delimiters" in data["coverage"]["checks"]
    assert data["coverage"]["limitations"]

    issue = data["issues"][0]
    assert issue["severity"] == "medium"
    assert issue["message"]
    assert issue["cause"] == "empty_assignment"
    assert issue["line"] == 1

    messages = [item["message"] for item in data["issues"]]
    assert not any("Python syntax" in message for message in messages)
    assert "Python syntax" not in data["summary"]


@pytest.mark.parametrize(
    ("source", "expected_language"),
    [
        (
            '<!doctype html><html lang="en"><head><title>T</title></head>'
            "<body></body></html>",
            "html",
        ),
        ("body { color: red; }", "css"),
        ("User Function X()\nLocal a := 1\nReturn a\n", "advpl"),
    ],
)
def test_agents_code_detects_language_from_content(
    source: str,
    expected_language: str,
) -> None:
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/agents/code",
        json={"project_name": "mixed", "source_code": source},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["agent"] == "language_agent"
    assert data["language"] == expected_language
    assert data["language_source"] == "content"
    assert data["confidence"] > 0.6


def test_agents_code_minimal_javascript_function_is_javascript() -> None:
    """The reproduced snippet must not be routed to the ADVPL validator.

    A bare ``function`` header is idiomatic JavaScript; before the detector
    weighting fix it outranked the JavaScript markers and produced a false
    ``unclosed_block`` ADVPL issue.
    """
    from app.main import app

    client = TestClient(app)
    source = (
        "function check(value) {\n"
        "  if (value = 10) {\n"
        "    return true;\n"
        "  }\n"
        "  return value;\n"
        "}\n"
    )
    response = client.post(
        "/agents/code",
        json={
            "project_name": "js-without-extension",
            "source_code": source,
            "language": "auto",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["language"] == "javascript"
    assert data["language_source"] == "content"
    assert data["confidence"] == 0.68
    assert not any(
        issue["cause"] == "unclosed_block" for issue in data["issues"]
    )


def test_agents_code_enriches_the_python_syntax_issue() -> None:
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/agents/code",
        json={
            "project_name": "python-project",
            "source_code": "def compute_total(items)\n    return sum(items)\n",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["agent"] == "code_agent"
    assert data["language"] == "python"
    assert data["score"] == 0
    # The Python flow predates structural coverage; it keeps the historical
    # "evaluated" default until Phase B wires the PythonValidator.
    assert data["score_status"] == "evaluated"

    # The legacy fields keep their exact values; the additive fields explain
    # the cause and the precise location without changing the historical ones.
    issue = data["issues"][0]
    assert issue["severity"] == "critical"
    assert issue["message"] == "expected ':'"
    assert issue["line"] == 1
    assert issue["cause"] == "python_syntax"
    assert issue["column"] == 25
    assert issue["rule_id"] == "python_syntax_error"


def test_create_analysis_with_repository_context_adds_relations_only(
    analysis_client,
) -> None:
    client = analysis_client
    html_source = (
        "<html><head>"
        '<link rel="stylesheet" href="css/style.css">'
        '<script src="js/app.js"></script></head>'
        '<body><img src="missing.png"></body></html>'
    )

    response = client.post(
        "/analyses",
        json={
            "task": "code",
            "project_name": "mixed",
            "source_code": "const value = 1;\n",
            "file_path": "js/app.js",
            "repository_context": {
                "files": [
                    {"path": "index.html", "source_code": html_source},
                    {"path": "css/style.css", "source_code": "body { color: red; }"},
                ],
                "paths": [
                    "index.html",
                    "css/style.css",
                    "js/app.js",
                ],
                "tree_complete": True,
                "apps_json": {"applications": {"job": {}}},
                "apps_json_path": "apps.json",
            },
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()["result"]

    # Relations are metadata: the deterministic analysis is untouched.
    assert result["language"] == "javascript"
    assert result["score"] == 100
    assert result["issues"] == []
    assert result["score_status"] == "evaluated"
    assert result["coverage"]["javascript"]["score_status"] == "evaluated"

    relations = result["relations"]
    assert relations["version"] == 1
    assert relations["tree_complete"] is True
    assert relations["summary"] == {
        "resolved": 2,
        "missing": 1,
        "external": 0,
        "unknown": 0,
    }
    assert relations["protheus"]["apps_json"] == {
        "path": "apps.json",
        "present": True,
        "parsed": True,
        "applications": 1,
        "keys": ["applications"],
    }
    assert result["report"]["relations"] == relations


def test_create_analysis_multilanguage_full_analysis_uses_the_report_agent(
    analysis_client,
) -> None:
    client = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "css-project",
            "source_code": "body { color: red; ",
            "file_path": "style.css",
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()["result"]

    assert result["language"] == "css"
    assert result["language_source"] == "extension"
    assert result["score"] == 50
    assert result["issues"]
    assert result["score_status"] == "evaluated"
    assert result["coverage"]["css"]["checks"]
    assert result["report"]["agent"] == "language_report_agent"
    assert list(result["report"]["analyses"]) == ["css"]
    assert "relations" not in result


def test_unknown_language_analysis_is_flagged_as_not_evaluated(
    analysis_client,
) -> None:
    client = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "unknown-project",
            "source_code": "prose without code markers\n",
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()["result"]

    assert result["language"] == "unknown"
    assert result["validation_skipped"] is True
    assert result["score_status"] == "skipped"
    assert result["score"] == 100
    assert result["coverage"]["unknown"]["score_status"] == "skipped"
    assert result["report"]["analyses"]["unknown"]["validation_skipped"] is True


def test_short_advpl_snippet_is_auto_detected_and_blocks_are_checked(
    analysis_client,
) -> None:
    client = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "reproduced-advpl",
            "source_code": 'If nX > 1\n    MsgInfo("positivo")\n',
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()["result"]

    assert result["language"] == "advpl"
    assert result["validation_skipped"] is False
    assert any(
        issue["cause"] == "unclosed_block" for issue in result["issues"]
    )


def test_detected_advpl_analysis_is_not_flagged_as_skipped(
    analysis_client,
) -> None:
    client = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "advpl-project",
            "source_code": "User Function X()\nLocal a := 1\nReturn a\n",
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()["result"]

    assert result["language"] == "advpl"
    assert result["validation_skipped"] is False


@pytest.mark.parametrize(
    ("settings_overrides", "files"),
    [
        (
            {"github_max_files": 1},
            [
                {"path": "a.js", "source_code": "const a = 1;\n"},
                {"path": "b.js", "source_code": "const b = 2;\n"},
            ],
        ),
        (
            {"github_max_file_bytes": 5},
            [{"path": "a.js", "source_code": "const a = 1;\n"}],
        ),
        (
            {"github_max_total_bytes": 10},
            [
                {"path": "a.js", "source_code": "const a = 1;\n"},
                {"path": "b.js", "source_code": "const b = 2;\n"},
            ],
        ),
    ],
)
def test_create_analysis_rejects_oversized_repository_context(
    analysis_client,
    monkeypatch,
    settings_overrides,
    files,
) -> None:
    from app.services import analysis as analysis_service

    client = analysis_client
    settings = {
        "max_source_code_bytes": 1_000_000,
        "github_max_files": 1_000,
        "github_max_file_bytes": 1_000_000,
        "github_max_total_bytes": 5_000_000,
        **settings_overrides,
    }
    monkeypatch.setattr(
        analysis_service,
        "get_settings",
        lambda: SimpleNamespace(**settings),
    )

    response = client.post(
        "/analyses",
        json={
            "task": "code",
            "project_name": "too-big",
            "source_code": "const value = 1;\n",
            "repository_context": {"files": files, "paths": ["a.js", "b.js"]},
        },
    )

    assert response.status_code == 413, response.text
    assert "limit" in response.json()["detail"].lower()


def test_create_analysis_rejects_too_many_repository_paths(
    analysis_client,
    monkeypatch,
) -> None:
    from app.services import analysis as analysis_service

    client = analysis_client
    settings = {
        "max_source_code_bytes": 1_000_000,
        "github_max_files": 1_000,
        "github_max_file_bytes": 1_000_000,
        "github_max_total_bytes": 5_000_000,
        "github_max_tree_paths": 2,
    }
    monkeypatch.setattr(
        analysis_service,
        "get_settings",
        lambda: SimpleNamespace(**settings),
    )

    response = client.post(
        "/analyses",
        json={
            "task": "code",
            "project_name": "too-many-paths",
            "source_code": "const value = 1;\n",
            "repository_context": {
                "files": [],
                "paths": [f"src/file-{index}.js" for index in range(5)],
                "tree_complete": True,
            },
        },
    )

    assert response.status_code == 413, response.text
    detail = response.json()["detail"].lower()
    assert "paths" in detail
    assert "limit" in detail


@pytest.mark.parametrize(
    "repository_context",
    [
        {
            "files": [{"path": "../secret.js", "source_code": "const a = 1;\n"}],
            "paths": ["../secret.js"],
        },
        {
            "files": [{"path": "/etc/passwd", "source_code": "root:x:0:0\n"}],
            "paths": ["/etc/passwd"],
        },
        {
            "files": [{"path": "a\x00b.js", "source_code": "const a = 1;\n"}],
            "paths": ["a\x00b.js"],
        },
    ],
)
def test_create_analysis_rejects_unsafe_repository_paths(
    analysis_client,
    repository_context,
) -> None:
    client = analysis_client

    response = client.post(
        "/analyses",
        json={
            "task": "code",
            "project_name": "unsafe",
            "source_code": "const value = 1;\n",
            "repository_context": repository_context,
        },
    )

    assert response.status_code == 422, response.text
