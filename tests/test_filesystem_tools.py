from pathlib import Path

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
    (project_root / "outside-link.txt").symlink_to(outside_file)

    tool = ListFilesTool(project_root=project_root)

    result = await tool.execute()

    assert result["status"] == "completed"
    assert result["files"] == ["inside.txt"]
