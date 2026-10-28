"""Regression tests for the orchestrator language gate.

The gate exists to guarantee that a non-Python source is never parsed with the
Python ``ast`` module (nor treated as Python by the legacy agents).
"""

from __future__ import annotations

import ast
from typing import Any

import pytest

from app.agents.orchestrator import OrchestratorAgent

JS_SOURCE = "const value = ;\n"
HTML_SOURCE = "<html><body><div></body></html>"
CSS_SOURCE = "body { color: red; "
ADVPL_SOURCE = "User Function X()\nLocal a := 1\nReturn a\n"


def _forbid_ast(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("ast.parse must not be called for non-Python sources")

    monkeypatch.setattr(ast, "parse", fail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "path"),
    [
        (JS_SOURCE, "app.js"),
        (HTML_SOURCE, "index.html"),
        (CSS_SOURCE, "style.css"),
        (ADVPL_SOURCE, "program.prw"),
    ],
)
async def test_orchestrator_never_parses_non_python_code(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    path: str,
) -> None:
    _forbid_ast(monkeypatch)

    result = await OrchestratorAgent().execute(
        {
            "task": "code",
            "project_name": "mixed",
            "source_code": source,
            "file_path": path,
        }
    )

    assert result["status"] == "completed"
    assert result["delegated_to"] == ["language_agent"]
    assert result["result"]["agent"] == "language_agent"


@pytest.mark.asyncio
@pytest.mark.parametrize("task", ["tests", "docs"])
async def test_orchestrator_routes_tests_and_docs_to_the_language_agent(
    monkeypatch: pytest.MonkeyPatch,
    task: str,
) -> None:
    _forbid_ast(monkeypatch)

    result = await OrchestratorAgent().execute(
        {
            "task": task,
            "project_name": "mixed",
            "source_code": JS_SOURCE,
            "file_path": "app.js",
        }
    )

    assert result["status"] == "completed"
    assert result["delegated_to"] == ["language_agent"]
    assert result["result"]["requested_task"] == task


@pytest.mark.asyncio
async def test_orchestrator_routes_language_full_analysis_to_the_report_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_ast(monkeypatch)

    result = await OrchestratorAgent().execute(
        {
            "task": "full_analysis",
            "project_name": "mixed",
            "source_code": CSS_SOURCE,
            "file_path": "style.css",
        }
    )

    assert result["status"] == "completed"
    assert result["delegated_to"] == ["language_agent", "language_report_agent"]

    report = result["result"]["report"]
    assert report["agent"] == "language_report_agent"
    assert report["requested_task"] == "full_analysis"
    assert list(report["analyses"]) == ["css"]
    assert report["analyses"]["css"]["agent"] == "language_agent"


@pytest.mark.asyncio
async def test_orchestrator_language_request_wins_over_python_like_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_ast(monkeypatch)

    result = await OrchestratorAgent().execute(
        {
            "task": "code",
            "project_name": "mixed",
            "source_code": "def looks_like_python():\n    return 1\n",
            "language": "javascript",
        }
    )

    assert result["delegated_to"] == ["language_agent"]
    assert result["result"]["language"] == "javascript"
    assert result["result"]["language_source"] == "manual"


@pytest.mark.asyncio
async def test_orchestrator_keeps_python_on_the_legacy_code_agent() -> None:
    result = await OrchestratorAgent().execute(
        {
            "task": "code",
            "project_name": "python-project",
            "source_code": "def hello():\n    return 'hello'\n",
        }
    )

    assert result["status"] == "completed"
    assert result["delegated_to"] == "code_agent"
    assert result["result"]["agent"] == "code_agent"
    assert result["result"]["score"] == 100


@pytest.mark.asyncio
async def test_orchestrator_keeps_the_legacy_python_full_analysis() -> None:
    result = await OrchestratorAgent().execute(
        {
            "task": "full_analysis",
            "project_name": "python-project",
            "source_code": (
                "def test_health():\n"
                '    """Test application health."""\n'
                "    assert True\n"
            ),
        }
    )

    assert result["delegated_to"] == [
        "code_agent",
        "test_agent",
        "docs_agent",
        "report_agent",
    ]
    assert result["result"]["report"]["agent"] == "report_agent"


@pytest.mark.asyncio
@pytest.mark.parametrize("task", ["tests", "docs"])
async def test_orchestrator_keeps_python_tests_and_docs_on_legacy_agents(
    task: str,
) -> None:
    result = await OrchestratorAgent().execute(
        {
            "task": task,
            "project_name": "python-project",
            "source_code": "def test_health():\n    assert True\n",
        }
    )

    expected = "test_agent" if task == "tests" else "docs_agent"
    assert result["delegated_to"] == expected


@pytest.mark.asyncio
async def test_orchestrator_unknown_task_keeps_the_exact_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_ast(monkeypatch)

    result = await OrchestratorAgent().execute(
        {
            "task": "security",
            "project_name": "mixed",
            "source_code": JS_SOURCE,
        }
    )

    assert result["status"] == "error"
    assert result["message"] == "No agent available for task: security"
