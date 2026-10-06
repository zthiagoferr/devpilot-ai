from __future__ import annotations

import inspect
import json
from pathlib import Path, PureWindowsPath
from typing import Any

from app.agents.base import BaseAgent
from app.services.llm_service import LLMService

from app.tools.filesystem import ListFilesTool


class PlanningAgent(BaseAgent):
    """Convert a development goal into a validated, multi-file implementation plan."""

    def __init__(self, llm_service: LLMService, project_root: Path) -> None:
        super().__init__(
            name="planning_agent",
            responsibility=(
                "Convert a high-level development goal into a validated multi-file plan."
            ),
        )
        self.llm_service = llm_service
        self.project_root = Path(project_root).resolve()

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        development_goal = context.get("development_goal")
        base_result = {
            "agent": self.name,
            "development_goal": development_goal,
            "file_tasks": [],
        }

        if not isinstance(development_goal, str) or not development_goal.strip():
            return {**base_result, "status": "error", "message": "A development_goal is required."}

        try:
            files = await self._get_safe_file_list()
            prompt = self._build_prompt(development_goal, files)
            response = await self._generate(prompt)
            content = self._response_content(response)
            plan = json.loads(content)
            file_tasks = self._validate_plan(plan)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return {**base_result, "status": "error", "message": str(exc)}
        except Exception as exc:
            return {**base_result, "status": "error", "message": f"Planning failed: {exc}"}

        return {
            "agent": self.name,
            "status": "completed",
            "development_goal": development_goal,
            "file_tasks": file_tasks,
        }

    async def _get_safe_file_list(self) -> list[str]:
        try:
            tool = ListFilesTool(project_root=self.project_root)
        except TypeError:
            tool = ListFilesTool(self.project_root)

        operation = getattr(tool, "execute", None)
        if operation is None:
            operation = getattr(tool, "run", None)
        if operation is None:
            operation = getattr(tool, "list_files", None)
        if operation is None:
            raise ValueError("ListFilesTool has no executable operation.")

        try:
            result = operation()
        except TypeError:
            result = operation(self.project_root)
        if inspect.isawaitable(result):
            result = await result

        if isinstance(result, dict):
            for key in ("files", "file_paths", "file_list"):
                if key in result:
                    result = result[key]
                    break
        if not isinstance(result, (list, tuple)):
            raise ValueError("ListFilesTool returned an invalid file list.")

        return [str(path) for path in result if isinstance(path, (str, Path))]

    def _build_prompt(self, development_goal: str, files: list[str]) -> str:
        return (
            "Create a precise implementation plan for the development goal below.\n\n"
            f"Development goal:\n{development_goal}\n\n"
            "Safe repository file list:\n"
            f"{json.dumps(files, ensure_ascii=False)}\n\n"
            "Return strict JSON only, with exactly this useful shape: "
            '{"file_tasks":[{"file_path":"relative/path","task":"specific task"}]}.'
            " Do not use Markdown fences or any explanatory text."
        )

    async def _generate(self, prompt: str) -> Any:
        generate = getattr(self.llm_service, "generate", None)
        if generate is None:
            generate = getattr(self.llm_service, "complete", None)
        if generate is None:
            raise ValueError("LLMService has no generation method.")

        result = generate(
            prompt,
            system_prompt=(
                "You are a planning assistant. Produce only valid JSON matching the "
                "requested schema. Never write files, run commands, or implement code."
            ),
        )
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _response_content(response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            content = response.get("content")
        else:
            content = getattr(response, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned no JSON content.")
        return content

    def _validate_plan(self, plan: Any) -> list[dict[str, str]]:
        if not isinstance(plan, dict):
            raise ValueError("LLM response must be a JSON object.")
        file_tasks = plan.get("file_tasks")
        if not isinstance(file_tasks, list) or not file_tasks:
            raise ValueError("file_tasks must be a non-empty list.")
        if len(file_tasks) > 12:
            raise ValueError("Plans may contain at most 12 files.")

        validated: list[dict[str, str]] = []
        seen: set[str] = set()
        for entry in file_tasks:
            if not isinstance(entry, dict):
                raise ValueError("Every file task must be an object.")
            file_path = entry.get("file_path")
            task = entry.get("task")
            if not isinstance(file_path, str) or not file_path.strip():
                raise ValueError("Every file task requires a file_path.")
            if not isinstance(task, str) or not task.strip():
                raise ValueError("Every file task requires a task.")

            path_text = file_path.strip()
            slash_parts = path_text.replace("\\", "/").split("/")
            windows_path = PureWindowsPath(path_text)
            path = Path(path_text)
            if (
                path.is_absolute()
                or windows_path.is_absolute()
                or windows_path.drive
                or ".." in slash_parts
                or any(part in {".env", ".git", ".venv"} for part in slash_parts)
            ):
                raise ValueError(f"Unsafe file path: {file_path}")

            resolved = (self.project_root / path).resolve()
            try:
                resolved.relative_to(self.project_root)
            except ValueError as exc:
                raise ValueError(f"File path is outside project_root: {file_path}") from exc

            key = path.as_posix()
            if key in seen:
                raise ValueError(f"Duplicate file path: {file_path}")
            seen.add(key)
            validated.append({"file_path": path_text, "task": task.strip()})

        return validated
