from os import walk
from pathlib import Path
from typing import Any

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
    target = (project_root / Path(file_path)).resolve()

    if not target.is_relative_to(project_root):
        return None, "Access outside the project is not allowed."

    relative_parts = target.relative_to(project_root).parts
    if any(part.casefold() in _SENSITIVE_PATH_NAMES for part in relative_parts):
        return None, "Access to sensitive project paths is not allowed."

    return target, None


class ListFilesTool(BaseTool):
    """Lists safe regular files located inside the project directory."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name="list_files",
            description="List safe regular files in the project.",
        )
        self._project_root = project_root.resolve()

    async def execute(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
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
        return {
            "status": "completed",
            "files": files,
        }


class ReadFileTool(BaseTool):
    """Reads files located inside the project directory."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name="read_file",
            description="Read the contents of a project file.",
        )
        self._project_root = project_root.resolve()

    async def execute(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        file_path = kwargs.get("path")

        if not file_path:
            return {
                "status": "error",
                "message": "File path was not provided.",
            }

        target, error = _resolve_project_path(self._project_root, file_path)
        if error:
            return {
                "status": "error",
                "message": error,
            }

        if not target.is_file():
            return {
                "status": "error",
                "message": f"File not found: {file_path}",
            }

        return {
            "status": "completed",
            "path": str(file_path),
            "content": target.read_text(encoding="utf-8"),
        }


class WriteFileTool(BaseTool):
    """Writes files located inside the project directory."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name="write_file",
            description="Create or update a project file.",
        )
        self._project_root = project_root.resolve()

    async def execute(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        file_path = kwargs.get("path")
        content = kwargs.get("content")

        if not file_path:
            return {
                "status": "error",
                "message": "File path was not provided.",
            }

        if content is None:
            return {
                "status": "error",
                "message": "File content was not provided.",
            }

        target, error = _resolve_project_path(self._project_root, file_path)
        if error:
            return {
                "status": "error",
                "message": error,
            }

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            str(content),
            encoding="utf-8",
        )

        return {
            "status": "completed",
            "path": str(file_path),
        }
