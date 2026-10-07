from os import walk
from pathlib import Path
from typing import Any, Mapping

from app.tools.base import BaseTool


_SENSITIVE_PATH_NAMES = {".env", ".git", ".venv"}
_LIST_EXCLUDED_DIRECTORY_NAMES = _SENSITIVE_PATH_NAMES | {
    "__pycache__",
    ".pytest_cache",
}


def _resolve_project_path(
    project_root: Path,
    file_path: str | Path,
) -> tuple[Path | None, str | None]:
    """Resolve a path and enforce project and sensitive-path boundaries."""
    try:
        target = (project_root / Path(file_path)).resolve()
    except (TypeError, ValueError, OSError):
        return None, "The file path is invalid."

    if not target.is_relative_to(project_root):
        return None, "Access outside the project is not allowed."

    relative_parts = target.relative_to(project_root).parts
    if any(part.casefold() in _SENSITIVE_PATH_NAMES for part in relative_parts):
        return None, "Access to sensitive project paths is not allowed."

    return target, None


def _set_tool_schema(tool: BaseTool, schema: dict[str, Any]) -> None:
    """Attach the V5 schema under the common names used by tool consumers."""
    tool.input_schema = schema  # type: ignore[attr-defined]
    tool.inputSchema = schema  # type: ignore[attr-defined]
    tool.schema = schema  # type: ignore[attr-defined]


def _tool_definition(tool: BaseTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,  # type: ignore[attr-defined]
    }


class ListFilesTool(BaseTool):
    """Lists safe regular files located inside the project directory."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name="list_files",
            description="List safe regular files in the project.",
        )
        self._project_root = project_root.resolve()
        _set_tool_schema(
            self,
            {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        files: list[str] = []

        for directory, dirnames, filenames in walk(
            self._project_root,
            topdown=True,
            followlinks=False,
        ):
            dirnames[:] = [
                name
                for name in dirnames
                if name.casefold() not in _LIST_EXCLUDED_DIRECTORY_NAMES
            ]

            directory_path = Path(directory)
            for filename in filenames:
                candidate = directory_path / filename
                target, error = _resolve_project_path(
                    self._project_root,
                    candidate,
                )
                if error or target is None or not target.is_file():
                    continue

                relative_path = target.relative_to(self._project_root).as_posix()
                if relative_path not in files:
                    files.append(relative_path)

        files.sort()
        return {"status": "completed", "files": files}

    def definition(self) -> dict[str, Any]:
        return _tool_definition(self)


class ReadFileTool(BaseTool):
    """Reads files located inside the project directory."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name="read_file",
            description="Read the contents of a project file.",
        )
        self._project_root = project_root.resolve()
        _set_tool_schema(
            self,
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative path of the file to read.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        file_path = kwargs.get("path")

        if not file_path:
            return {"status": "error", "message": "File path was not provided."}

        target, error = _resolve_project_path(self._project_root, file_path)
        if error:
            return {"status": "error", "message": error}

        if target is None or not target.is_file():
            return {"status": "error", "message": f"File not found: {file_path}"}

        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return {"status": "error", "message": f"Unable to read file: {exc}"}

        return {"status": "completed", "path": str(file_path), "content": content}

    def definition(self) -> dict[str, Any]:
        return _tool_definition(self)


class WriteFileTool(BaseTool):
    """Writes files located inside the project directory."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name="write_file",
            description="Create or update a project file.",
        )
        self._project_root = project_root.resolve()
        _set_tool_schema(
            self,
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Project-relative path of the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "UTF-8 text to write to the file.",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        file_path = kwargs.get("path")
        content = kwargs.get("content")

        if not file_path:
            return {"status": "error", "message": "File path was not provided."}
        if content is None:
            return {"status": "error", "message": "File content was not provided."}

        target, error = _resolve_project_path(self._project_root, file_path)
        if error:
            return {"status": "error", "message": error}
        if target is None:
            return {"status": "error", "message": "The file path is invalid."}

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
        except OSError as exc:
            return {"status": "error", "message": f"Unable to write file: {exc}"}

        return {"status": "completed", "path": str(file_path)}

    def definition(self) -> dict[str, Any]:
        return _tool_definition(self)


_FILESYSTEM_TOOL_TYPES = (ListFilesTool, ReadFileTool, WriteFileTool)


def register_filesystem_tools(project_root: Path) -> dict[str, BaseTool]:
    """Create the filesystem tools in a deterministic, name-keyed registry."""
    tools = [tool_type(project_root) for tool_type in _FILESYSTEM_TOOL_TYPES]
    return {tool.name: tool for tool in tools}


def get_filesystem_tools(project_root: Path) -> dict[str, BaseTool]:
    """Compatibility alias for callers that obtain rather than register tools."""
    return register_filesystem_tools(project_root)


async def invoke_filesystem_tool(
    tools: Mapping[str, BaseTool],
    name: str,
    arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Safely invoke a registered filesystem capability by its exact name."""
    tool = tools.get(name)
    if tool is None or not isinstance(tool, _FILESYSTEM_TOOL_TYPES):
        return {"status": "error", "message": f"Unknown filesystem tool: {name}"}
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, Mapping):
        return {"status": "error", "message": "Tool arguments must be an object."}
    return await tool.execute(**dict(arguments))
