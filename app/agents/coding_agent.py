import json
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.services.llm_service import LLMService
from app.tools.filesystem import ReadFileTool, WriteFileTool
from app.tools.testing import RunTestsTool


class CodingAgent(BaseAgent):
    """Uses an LLM and project tools to implement coding tasks."""

    def __init__(
        self,
        llm_service: LLMService,
        project_root: Path,
        max_attempts: int = 3,
    ) -> None:
        super().__init__(
            name="coding_agent",
            responsibility="Implement coding tasks and validate changes.",
        )

        self._llm_service = llm_service
        self._read_file = ReadFileTool(project_root)
        self._write_file = WriteFileTool(project_root)
        self._run_tests = RunTestsTool(project_root)
        self._max_attempts = max_attempts

    async def execute(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        task = context.get("task")
        file_path = context.get("file_path")

        if not task:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Coding task was not provided.",
            }

        if not file_path:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Target file was not provided.",
            }

        file_result = await self._read_file.execute(
            path=file_path,
        )

        if file_result["status"] == "completed":
            current_content = file_result["content"]
        else:
            current_content = ""

        test_output = ""

        for attempt in range(1, self._max_attempts + 1):
            prompt = self._build_prompt(
                task=task,
                file_path=file_path,
                current_content=current_content,
                test_output=test_output,
            )

            response = await self._llm_service.generate(
                prompt,
                system_prompt=(
                    "You are a senior Python coding agent. "
                    "Implement the requested task. "
                    "Return the complete target file, not a patch. "
                    "Fix any test failures provided to you. "
                    "Return only valid JSON. "
                    "Do not include Markdown."
                ),
            )

            try:
                generated = json.loads(response.content)
                new_content = generated["content"]
            except (json.JSONDecodeError, KeyError, TypeError):
                return {
                    "agent": self.name,
                    "status": "error",
                    "message": "LLM returned an invalid coding response.",
                }

            write_result = await self._write_file.execute(
                path=file_path,
                content=new_content,
            )

            if write_result["status"] != "completed":
                return {
                    "agent": self.name,
                    "status": "error",
                    "message": write_result["message"],
                }

            test_result = await self._run_tests.execute()

            if test_result["status"] == "completed":
                return {
                    "agent": self.name,
                    "status": "completed",
                    "model": response.model,
                    "file": file_path,
                    "attempts": attempt,
                    "tests": test_result,
                }

            current_content = new_content
            test_output = (
                test_result["stdout"]
                + "\n"
                + test_result["stderr"]
            )

        return {
            "agent": self.name,
            "status": "tests_failed",
            "file": file_path,
            "attempts": self._max_attempts,
            "tests": test_result,
        }

    def _build_prompt(
        self,
        *,
        task: str,
        file_path: str,
        current_content: str,
        test_output: str,
    ) -> str:
        prompt = (
            f"Task:\n{task}\n\n"
            f"Target file:\n{file_path}\n\n"
            f"Current content:\n{current_content}\n"
        )

        if test_output:
            prompt += (
                "\nPrevious test execution failed.\n"
                "Test output:\n"
                f"{test_output}\n"
            )

        prompt += (
            "\nReturn only valid JSON with this structure:\n"
            '{"content": "complete file content"}'
        )

        return prompt