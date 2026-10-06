from pathlib import Path
from typing import Any

import pytest

from app.agents.development_agent import DevelopmentAgent


class StubCodingAgent:
    """Deterministic CodingAgent replacement used without an LLM or network."""

    def __init__(self, project_root: Path, behaviors: dict[str, Any]) -> None:
        self.project_root = project_root
        self.behaviors = behaviors
        self.calls: list[dict[str, Any]] = []

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(context.copy())
        file_path = context["file_path"]
        behavior = self.behaviors[file_path]
        target = self.project_root / file_path

        if "content" in behavior:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(behavior["content"], encoding="utf-8")

        return {
            "agent": "coding_agent",
            "status": behavior["status"],
            "file": file_path,
            "message": behavior.get("message", ""),
        }


def _assert_completed_task(entry: Any, file_path: str) -> None:
    """DevelopmentAgent records completed task descriptors in its result."""
    assert isinstance(entry, dict)
    assert entry["file_path"] == file_path
    assert isinstance(entry.get("task"), str)
    assert entry["task"]


@pytest.mark.asyncio
async def test_development_agent_executes_multiple_files_sequentially(
    tmp_path: Path,
) -> None:
    stub = StubCodingAgent(
        tmp_path,
        {
            "src/one.py": {"status": "completed", "content": "ONE = 1\n"},
            "src/two.py": {"status": "completed", "content": "TWO = 2\n"},
        },
    )
    agent = DevelopmentAgent(coding_agent=stub, project_root=tmp_path)

    result = await agent.execute(
        {
            "development_goal": "Create the two modules.",
            "file_tasks": [
                {"file_path": "src/one.py", "task": "Create one."},
                {"file_path": "src/two.py", "task": "Create two."},
            ],
        }
    )

    assert result["agent"] == "development_agent"
    assert result["status"] == "completed"
    assert [call["file_path"] for call in stub.calls] == [
        "src/one.py",
        "src/two.py",
    ]
    assert [call["task"] for call in stub.calls] == [
        "Create one.",
        "Create two.",
    ]
    assert (tmp_path / "src/one.py").read_text(encoding="utf-8") == "ONE = 1\n"
    assert (tmp_path / "src/two.py").read_text(encoding="utf-8") == "TWO = 2\n"
    assert len(result["completed_tasks"]) == 2
    _assert_completed_task(result["completed_tasks"][0], "src/one.py")
    _assert_completed_task(result["completed_tasks"][1], "src/two.py")


@pytest.mark.asyncio
async def test_rollback_restores_all_existing_files_when_later_task_fails(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("first original\n", encoding="utf-8")
    second.write_text("second original\n", encoding="utf-8")

    stub = StubCodingAgent(
        tmp_path,
        {
            "first.py": {"status": "completed", "content": "first changed\n"},
            "second.py": {
                "status": "error",
                "content": "second changed before failing\n",
                "message": "coding failed",
            },
        },
    )
    agent = DevelopmentAgent(coding_agent=stub, project_root=tmp_path)

    result = await agent.execute(
        {
            "development_goal": "Update both files.",
            "file_tasks": [
                {"file_path": "first.py", "task": "Update first."},
                {"file_path": "second.py", "task": "Update second."},
            ],
        }
    )

    assert result["status"] == "failed"
    assert first.read_text(encoding="utf-8") == "first original\n"
    assert second.read_text(encoding="utf-8") == "second original\n"
    assert len(result["completed_tasks"]) == 1
    _assert_completed_task(result["completed_tasks"][0], "first.py")


@pytest.mark.asyncio
async def test_rollback_deletes_new_files_created_before_later_failure(
    tmp_path: Path,
) -> None:
    stub = StubCodingAgent(
        tmp_path,
        {
            "created.py": {"status": "completed", "content": "created\n"},
            "failed.py": {
                "status": "error",
                "content": "failed\n",
                "message": "coding failed",
            },
        },
    )
    agent = DevelopmentAgent(coding_agent=stub, project_root=tmp_path)

    result = await agent.execute(
        {
            "development_goal": "Create both files.",
            "file_tasks": [
                {"file_path": "created.py", "task": "Create the first file."},
                {"file_path": "failed.py", "task": "Create the second file."},
            ],
        }
    )

    assert result["status"] == "failed"
    assert not (tmp_path / "created.py").exists()
    assert not (tmp_path / "failed.py").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_path",
    [
        "../outside.py",
        ".env",
        ".git/config",
        ".venv/bin/python",
    ],
)
async def test_rejects_unsafe_file_paths(tmp_path: Path, file_path: str) -> None:
    stub = StubCodingAgent(tmp_path, {})
    agent = DevelopmentAgent(coding_agent=stub, project_root=tmp_path)

    result = await agent.execute(
        {
            "development_goal": "Write a file.",
            "file_tasks": [{"file_path": file_path, "task": "Write it."}],
        }
    )

    assert result["agent"] == "development_agent"
    assert result["status"] == "error"
    assert stub.calls == []
    assert not (tmp_path / ".env").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [
        {},
        {"development_goal": "Goal"},
        {"file_tasks": []},
        {"development_goal": "Goal", "file_tasks": "not a list"},
        {"development_goal": "Goal", "file_tasks": [{"file_path": "x.py"}]},
        {"development_goal": "Goal", "file_tasks": [{"task": "Create it."}]},
        {"project_name": "wrong", "tasks": []},
    ],
)
async def test_rejects_invalid_or_missing_context(
    tmp_path: Path, context: dict[str, Any]
) -> None:
    stub = StubCodingAgent(tmp_path, {})
    agent = DevelopmentAgent(coding_agent=stub, project_root=tmp_path)

    result = await agent.execute(context)

    assert result["agent"] == "development_agent"
    assert result["status"] == "error"
    assert stub.calls == []
