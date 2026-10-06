from pathlib import Path
from typing import Any

from app.tools.base import BaseTool


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

        target = (self._project_root / file_path).resolve()

        if not target.is_relative_to(self._project_root):
            return {
                "status": "error",
                "message": "Access outside the project is not allowed.",
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

        target = (self._project_root / file_path).resolve()

        if not target.is_relative_to(self._project_root):
            return {
                "status": "error",
                "message": "Access outside the project is not allowed.",
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