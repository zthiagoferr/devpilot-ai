from pathlib import Path

import pytest

from app.tools.filesystem import ReadFileTool, WriteFileTool


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
