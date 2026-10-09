import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool


DENIED_PATHS = (".env", ".git/config", ".venv/pyvenv.cfg", "../outside.txt")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", DENIED_PATHS)
async def test_read_file_tool_denies_protected_paths(tmp_path, path):
    tool = ReadFileTool(project_root=tmp_path)

    result = await tool.execute(path=path)

    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", DENIED_PATHS)
async def test_write_file_tool_denies_protected_paths(tmp_path, path):
    tool = WriteFileTool(project_root=tmp_path)

    result = await tool.execute(path=path, content="must not be written")

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_read_file_tool_reads_env_example(tmp_path):
    env_example = tmp_path / ".env.example"
    env_example.write_text("EXAMPLE_SETTING=safe-value\n")

    tool = ReadFileTool(project_root=tmp_path)

    result = await tool.execute(path=".env.example")

    assert result["status"] == "completed"
    assert "content" in result
    assert result["content"] == "EXAMPLE_SETTING=safe-value\n"


@pytest.mark.asyncio
async def test_write_and_read_normal_project_file(tmp_path):
    content = "project file content"

    write_tool = WriteFileTool(project_root=tmp_path)
    write_result = await write_tool.execute(path="project.txt", content=content)

    assert write_result["status"] == "completed"

    read_tool = ReadFileTool(project_root=tmp_path)
    read_result = await read_tool.execute(path="project.txt")

    assert read_result["status"] == "completed"
    assert "content" in read_result
    assert read_result["content"] == content


@pytest.mark.asyncio
async def test_list_files_tool_returns_nested_regular_files_sorted_as_project_relative_posix_paths(
    tmp_path,
):
    (tmp_path / "zeta.txt").write_text("zeta")
    (tmp_path / "nested" / "deeper").mkdir(parents=True)
    (tmp_path / "nested" / "beta.txt").write_text("beta")
    (tmp_path / "nested" / "deeper" / "alpha.txt").write_text("alpha")

    tool = ListFilesTool(project_root=tmp_path)

    result = await tool.execute()

    assert result["status"] == "completed"
    assert result["files"] == [
        "nested/beta.txt",
        "nested/deeper/alpha.txt",
        "zeta.txt",
    ]


@pytest.mark.asyncio
async def test_list_files_tool_excludes_env_but_includes_env_example(tmp_path):
    (tmp_path / ".env").write_text("SECRET=not-for-listing")
    (tmp_path / ".env.example").write_text("EXAMPLE_SETTING=safe-value")

    tool = ListFilesTool(project_root=tmp_path)

    result = await tool.execute()

    assert result["status"] == "completed"
    assert ".env" not in result["files"]
    assert ".env.example" in result["files"]


@pytest.mark.asyncio
async def test_list_files_tool_excludes_files_in_protected_directories(tmp_path):
    protected_files = (
        (".git", "config"),
        (".venv", "pyvenv.cfg"),
        ("__pycache__", "module.pyc"),
        (".pytest_cache", "cache.json"),
    )
    for directory, filename in protected_files:
        protected_directory = tmp_path / directory
        protected_directory.mkdir()
        (protected_directory / filename).write_text("protected")

    (tmp_path / "visible.txt").write_text("visible")

    tool = ListFilesTool(project_root=tmp_path)

    result = await tool.execute()

    assert result["status"] == "completed"
    assert result["files"] == ["visible.txt"]


@pytest.mark.asyncio
async def test_list_files_tool_excludes_symlink_to_file_outside_project_root(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside project")
    (project_root / "inside.txt").write_text("inside project")
    try:
        (project_root / "outside-link.txt").symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("This platform does not permit creating symlinks.")

    tool = ListFilesTool(project_root=project_root)

    result = await tool.execute()

    assert result["status"] == "completed"
    assert result["files"] == ["inside.txt"]


# V5 runtime coverage

from app.tools import (
    Skill,
    SkillRegistry,
    ToolExecutionResult,
    ToolExecutor,
    ToolRegistry,
    create_default_project_registry,
)
from app.tools.base import BaseTool
from app.agents.base import BaseAgent


class _EchoTool(BaseTool):
    def __init__(self, name: str = "echo_test") -> None:
        super().__init__(
            name=name,
            description="A deterministic test tool.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"value": kwargs["value"]}


class _FailingTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="failing_test",
            description="A deterministic failing test tool.",
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(f"internal failure: {kwargs.get('secret')}")


def test_valid_tool_registration_and_lookup():
    registry = ToolRegistry()
    tool = _EchoTool()

    registry.register(tool)

    assert registry.lookup("echo_test") is tool
    assert registry.get("echo_test") is tool
    assert registry.lookup("missing") is None


def test_duplicate_and_invalid_tool_registration_are_rejected():
    registry = ToolRegistry()
    registry.register(_EchoTool())

    with pytest.raises(ValueError):
        registry.register(_EchoTool())

    with pytest.raises(TypeError):
        registry.register(object())


def test_tool_discovery_is_deterministically_sorted_and_json_serializable():
    registry = ToolRegistry()

    for name in ("z_tool", "a_tool", "m_tool"):
        registry.register(_EchoTool(name))

    discovered = registry.discovery_metadata()

    assert [item["name"] for item in discovered] == [
        "a_tool",
        "m_tool",
        "z_tool",
    ]
    json.dumps(discovered)


@pytest.mark.asyncio
async def test_tool_executor_returns_success_and_safe_failure_results():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    registry.register(_FailingTool())
    executor = ToolExecutor(registry)

    success = await executor.execute("echo_test", value="ok")

    assert isinstance(success, ToolExecutionResult)
    assert success.success is True
    assert success.status == "completed"
    assert success.output == {"value": "ok"}

    missing = await executor.execute(
        "missing_tool",
        value="SECRET_VALUE",
    )

    assert missing.success is False
    assert missing.status == "failed"
    assert missing.error == "Tool is not registered."
    assert "SECRET_VALUE" not in json.dumps(missing.to_dict())

    failed = await executor.execute(
        "failing_test",
        secret="TOP_SECRET",
    )

    assert failed.success is False
    assert failed.status == "failed"
    assert failed.error == "Tool execution failed."
    assert "TOP_SECRET" not in json.dumps(failed.to_dict())


def test_skill_and_skill_registry_behavior():
    tool = _EchoTool()
    skill = Skill(
        name="filesystem",
        description="Project files",
        tools=[tool],
    )
    registry = SkillRegistry()

    registry.register(skill)

    assert registry.lookup("filesystem") is skill
    assert registry.get("filesystem") is skill
    assert registry.lookup("missing") is None

    metadata = registry.discovery_metadata()
    assert metadata[0]["name"] == "filesystem"
    assert metadata[0]["tools"][0]["name"] == "echo_test"
    json.dumps(metadata)

    with pytest.raises(ValueError):
        registry.register(skill)

    with pytest.raises(TypeError):
        registry.register(object())


def test_tool_and_skill_registries_are_isolated():
    first_tools = ToolRegistry()
    second_tools = ToolRegistry()

    first_tools.register(_EchoTool())

    assert first_tools.lookup("echo_test") is not None
    assert second_tools.lookup("echo_test") is None

    first_skills = SkillRegistry()
    second_skills = SkillRegistry()
    first_skills.register(
        Skill(
            name="filesystem",
            description="Project files",
            tools=[_EchoTool()],
        )
    )

    assert first_skills.lookup("filesystem") is not None
    assert second_skills.lookup("filesystem") is None


@pytest.mark.asyncio
async def test_filesystem_traversal_workspace_and_secret_safe_errors(tmp_path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("TOP_SECRET")
    read = ReadFileTool(project_root=tmp_path)
    write = WriteFileTool(project_root=tmp_path)

    for tool, kwargs in (
        (read, {"path": str(outside)}),
        (read, {"path": "missing.txt"}),
        (write, {"path": "../outside-secret.txt", "content": "x"}),
    ):
        result = await tool.execute(**kwargs)
        assert result["status"] == "error"
        assert "TOP_SECRET" not in json.dumps(result)
        assert str(outside) not in json.dumps(result)


def test_approved_default_project_tools_and_no_arbitrary_shell_capability(tmp_path):
    registry = create_default_project_registry(tmp_path)
    discovered = registry.discovery_metadata()
    names = {item["name"] for item in discovered}

    assert {"list_files", "read_file", "write_file"}.issubset(names)
    assert not names.intersection(
        {"shell", "run_shell", "execute_command"}
    )


def test_default_project_registries_are_fresh_and_isolated(tmp_path):
    first = create_default_project_registry(tmp_path)
    second = create_default_project_registry(tmp_path)

    assert first is not second

    first.register(_EchoTool())

    assert first.lookup("echo_test") is not None
    assert second.lookup("echo_test") is None


class _EchoAgent(BaseAgent):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__(
            name="echo_agent",
            responsibility="Invoke a registered tool.",
            tool_registry=registry,
        )

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"agent": self.name}


@pytest.mark.asyncio
async def test_base_agent_invokes_registered_tool_and_rejects_unknown():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    agent = _EchoAgent(registry)

    result = await agent.invoke_tool("echo_test", {"value": "ok"})

    assert result.output == {"value": "ok"}

    with pytest.raises(ValueError):
        await agent.invoke_tool("missing")
