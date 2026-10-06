import asyncio
import os
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool


class RunTestsTool(BaseTool):
    """Runs the project's pytest test suite."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name="run_tests",
            description="Run the project test suite with pytest.",
        )
        self._project_root = project_root.resolve()

    async def execute(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        test_path = kwargs.get("path")

        command = [
            "python",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
        ]

        if test_path:
            target = (self._project_root / test_path).resolve()

            if not target.is_relative_to(self._project_root):
                return {
                    "status": "error",
                    "message": "Access outside the project is not allowed.",
                }

            command.append(str(target))

        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=self._project_root,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "status": (
                "completed"
                if process.returncode == 0
                else "failed"
            ),
            "return_code": process.returncode,
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
        }