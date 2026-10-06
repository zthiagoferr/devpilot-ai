import json
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.services.llm_service import LLMService
from app.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool
from app.tools.testing import RunTestsTool


class CodingAgent(BaseAgent):
    """Uses an LLM and project tools to implement coding tasks."""

    _MAX_CONTEXT_FILES = 8
    _MAX_CONTEXT_CHARS = 12000
    _TEXT_EXTENSIONS = {
        ".cfg",
        ".ini",
        ".json",
        ".md",
        ".py",
        ".pyi",
        ".rst",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
    _EXCLUDED_PARTS = {
        ".git",
        ".venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        "build",
        "dist",
    }
    _EXCLUDED_NAMES = {".env", ".env.local", ".env.development", ".env.production"}

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
        self._project_root = project_root
        self._list_files = ListFilesTool(project_root)
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

        original_exists = file_result["status"] == "completed"
        if original_exists:
            original_content = file_result["content"]
            current_content = original_content
        else:
            original_content = ""
            current_content = ""

        repository_context = await self._build_repository_context(
            task=str(task),
            target_path=str(file_path),
        )
        test_output = ""

        for attempt in range(1, self._max_attempts + 1):
            prompt = self._build_prompt(
                task=task,
                file_path=file_path,
                current_content=current_content,
                test_output=test_output,
                repository_context=repository_context,
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

        await self._restore_original_file(
            file_path=file_path,
            existed=original_exists,
            content=original_content,
        )

        return {
            "agent": self.name,
            "status": "tests_failed",
            "file": file_path,
            "attempts": self._max_attempts,
            "tests": test_result,
        }

    async def _build_repository_context(
        self,
        *,
        task: str,
        target_path: str,
    ) -> str:
        try:
            listing = await self._list_files.execute(path=".")
        except Exception:
            return ""

        if isinstance(listing, dict):
            paths = listing.get("files", listing.get("paths", []))
        else:
            paths = listing
        if not isinstance(paths, list):
            return ""

        target = self._safe_relative_path(target_path)
        if target is None:
            target = target_path.replace("\\", "/").lstrip("./")

        task_words = {
            word.lower()
            for word in task.replace("_", " ").replace("-", " ").split()
            if len(word) >= 3
        }
        target_words = {
            word.lower()
            for word in Path(target).stem.replace("-", "_").split("_")
            if len(word) >= 3
        }

        candidates: list[tuple[int, str]] = []
        for entry in paths:
            if isinstance(entry, dict):
                candidate = entry.get("path") or entry.get("name")
            else:
                candidate = entry
            if not isinstance(candidate, str):
                continue
            relative = self._safe_relative_path(candidate)
            if relative is None or relative == target:
                continue
            path = Path(relative)
            if path.suffix.lower() not in self._TEXT_EXTENSIONS:
                continue

            lower_path = relative.lower()
            lower_parts = {part.lower() for part in path.parts}
            if lower_parts & self._EXCLUDED_PARTS:
                continue
            if path.name.lower() in self._EXCLUDED_NAMES:
                continue

            score = 0
            if path.suffix.lower() in {".py", ".pyi"}:
                score += 30
            if "test" in lower_path or path.name.startswith("test_"):
                score += 25
            score += sum(12 for word in target_words if word in lower_path)
            score += sum(5 for word in task_words if word in lower_path)
            candidates.append((score, relative))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[: self._MAX_CONTEXT_FILES]
        sections: list[str] = []
        remaining = self._MAX_CONTEXT_CHARS

        for _, relative in selected:
            if remaining <= 0:
                break

            try:
                result = await self._read_file.execute(path=relative)
            except Exception:
                continue

            if not isinstance(result, dict) or result.get("status") != "completed":
                continue

            content = result.get("content")
            if not isinstance(content, str):
                continue

            separator = "\n\n" if sections else ""
            header = f"File: {relative}\n"
            overhead = len(separator) + len(header)

            if overhead >= remaining:
                break

            content = content[: remaining - overhead]
            section = f"{header}{content}"

            sections.append(section)
            remaining -= overhead + len(content)

        return "\n\n".join(sections)

    def _safe_relative_path(self, value: str) -> str | None:
        normalized = value.replace("\\", "/")
        path = Path(normalized)
        if path.is_absolute() or ".." in path.parts:
            return None
        relative = normalized.lstrip("./")
        if not relative or relative.startswith("/"):
            return None
        return relative

    async def _restore_original_file(
        self,
        *,
        file_path: str,
        existed: bool,
        content: str,
    ) -> None:
        if existed:
            await self._write_file.execute(
                path=file_path,
                content=content,
            )
            return

        target_path = self._project_root / file_path
        if target_path.exists() or target_path.is_symlink():
            target_path.unlink()

    def _build_prompt(
        self,
        *,
        task: str,
        file_path: str,
        current_content: str,
        test_output: str,
        repository_context: str = "",
    ) -> str:
        prompt = (
            f"Task:\n{task}\n\n"
            f"Target file:\n{file_path}\n\n"
            f"Current content:\n{current_content}\n"
        )

        if repository_context:
            prompt += (
                "\nRelevant repository context (reference only; do not replace "
                "the task or target file):\n"
                f"{repository_context}\n"
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
