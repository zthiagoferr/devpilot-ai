import inspect
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
    _TOOL_NAMES = ("list_files", "read_file", "write_file", "run_tests")

    def __init__(
        self,
        llm_service: LLMService,
        project_root: Path,
        max_attempts: int = 3,
        tool_registry: Any | None = None,
        tool_executor: Any | None = None,
    ) -> None:
        super().__init__(
            name="coding_agent",
            responsibility="Implement coding tasks and validate changes.",
        )

        self._llm_service = llm_service
        self._project_root = project_root
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._tool_name_cache: dict[str, str] = {}

        # These remain the compatibility path for callers which do not inject
        # the V5 tool infrastructure.
        self._list_files = ListFilesTool(project_root)
        self._read_file = ReadFileTool(project_root)
        self._write_file = WriteFileTool(project_root)
        self._run_tests = RunTestsTool(project_root)
        self._max_attempts = max_attempts

    async def _tool(self, name: str, **arguments: Any) -> Any:
        """Invoke a named safe project operation through V5 when available."""
        if self._tool_executor is None:
            fallback = {
                "list_files": self._list_files,
                "read_file": self._read_file,
                "write_file": self._write_file,
                "run_tests": self._run_tests,
            }[name]
            return await fallback.execute(**arguments)

        tool_name = await self._resolve_tool_name(name)
        execute = getattr(self._tool_executor, "execute")
        signature = inspect.signature(execute)
        parameters = list(signature.parameters.values())
        named = {parameter.name for parameter in parameters}

        if "tool_name" in named:
            if "arguments" in named:
                result = execute(tool_name=tool_name, arguments=arguments)
            elif "parameters" in named:
                result = execute(tool_name=tool_name, parameters=arguments)
            elif "input" in named:
                result = execute(tool_name=tool_name, input=arguments)
            else:
                result = execute(tool_name=tool_name, **arguments)
        elif "name" in named and "tool" not in named:
            if "arguments" in named:
                result = execute(name=tool_name, arguments=arguments)
            else:
                result = execute(name=tool_name, **arguments)
        elif any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters):
            result = execute(tool_name, **arguments)
        else:
            result = execute(tool_name, arguments)

        if inspect.isawaitable(result):
            return await result
        return result

    async def _resolve_tool_name(self, canonical: str) -> str:
        if canonical in self._tool_name_cache:
            return self._tool_name_cache[canonical]

        names: list[str] = []
        registry = self._tool_registry
        if registry is not None:
            discover = getattr(registry, "discover", None)
            if discover is None:
                discover = getattr(registry, "list_tools", None)
            if discover is not None:
                discovered = discover()
                if inspect.isawaitable(discovered):
                    discovered = await discovered
                if isinstance(discovered, dict):
                    discovered = list(discovered.values())
                if isinstance(discovered, (list, tuple, set)):
                    for item in discovered:
                        if isinstance(item, str):
                            names.append(item)
                        elif isinstance(item, dict):
                            value = item.get("name") or item.get("tool_name") or item.get("id")
                            if isinstance(value, str):
                                names.append(value)
                        else:
                            value = getattr(item, "name", None)
                            if isinstance(value, str):
                                names.append(value)

        # Sorting makes aliases selected from registry metadata deterministic.
        names = sorted(set(names))
        selected = next((item for item in names if item == canonical), None)
        if selected is None:
            selected = next(
                (item for item in names if item.rsplit(".", 1)[-1] == canonical),
                canonical,
            )
        self._tool_name_cache[canonical] = selected
        return selected

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task")
        file_path = context.get("file_path")

        if not task:
            return {"agent": self.name, "status": "error", "message": "Coding task was not provided."}
        if not file_path:
            return {"agent": self.name, "status": "error", "message": "Target file was not provided."}

        file_result = await self._tool("read_file", path=file_path)
        original_exists = isinstance(file_result, dict) and file_result.get("status") == "completed"
        original_content = file_result.get("content", "") if original_exists else ""
        current_content = original_content

        repository_context = await self._build_repository_context(task=str(task), target_path=str(file_path))
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
                    "You are a senior Python coding agent. Implement the requested task. "
                    "Return the complete target file, not a patch. Fix any test failures provided to you. "
                    "Return only valid JSON. Do not include Markdown."
                ),
            )
            try:
                generated = json.loads(response.content)
                new_content = generated["content"]
            except (json.JSONDecodeError, KeyError, TypeError):
                return {"agent": self.name, "status": "error", "message": "LLM returned an invalid coding response."}

            write_result = await self._tool("write_file", path=file_path, content=new_content)
            if not isinstance(write_result, dict) or write_result.get("status") != "completed":
                return {"agent": self.name, "status": "error", "message": write_result.get("message", "Unable to write file.")}

            test_result = await self._tool("run_tests")
            if isinstance(test_result, dict) and test_result.get("status") == "completed":
                return {
                    "agent": self.name,
                    "status": "completed",
                    "model": response.model,
                    "file": file_path,
                    "attempts": attempt,
                    "tests": test_result,
                }
            current_content = new_content
            test_output = test_result.get("stdout", "") + "\n" + test_result.get("stderr", "")

        await self._restore_original_file(file_path=file_path, existed=original_exists, content=original_content)
        return {"agent": self.name, "status": "tests_failed", "file": file_path, "attempts": self._max_attempts, "tests": test_result}

    async def _build_repository_context(self, *, task: str, target_path: str) -> str:
        try:
            listing = await self._tool("list_files", path=".")
        except Exception:
            return ""
        paths = listing.get("files", listing.get("paths", [])) if isinstance(listing, dict) else listing
        if not isinstance(paths, list):
            return ""

        target = self._safe_relative_path(target_path) or target_path.replace("\\", "/").lstrip("./")
        task_words = {word.lower() for word in task.replace("_", " ").replace("-", " ").split() if len(word) >= 3}
        target_words = {word.lower() for word in Path(target).stem.replace("-", "_").split("_") if len(word) >= 3}
        candidates: list[tuple[int, str]] = []
        for entry in paths:
            candidate = entry.get("path") or entry.get("name") if isinstance(entry, dict) else entry
            if not isinstance(candidate, str):
                continue
            relative = self._safe_relative_path(candidate)
            if relative is None or relative == target or Path(relative).suffix.lower() not in self._TEXT_EXTENSIONS:
                continue
            path = Path(relative)
            if {part.lower() for part in path.parts} & self._EXCLUDED_PARTS or path.name.lower() in self._EXCLUDED_NAMES:
                continue
            lower = relative.lower()
            score = (30 if path.suffix.lower() in {".py", ".pyi"} else 0) + (25 if "test" in lower or path.name.startswith("test_") else 0)
            score += sum(12 for word in target_words if word in lower) + sum(5 for word in task_words if word in lower)
            candidates.append((score, relative))
        candidates.sort(key=lambda item: (-item[0], item[1]))

        sections: list[str] = []
        remaining = self._MAX_CONTEXT_CHARS
        for _, relative in candidates[: self._MAX_CONTEXT_FILES]:
            if remaining <= 0:
                break
            try:
                result = await self._tool("read_file", path=relative)
            except Exception:
                continue
            if not isinstance(result, dict) or result.get("status") != "completed" or not isinstance(result.get("content"), str):
                continue
            separator = "\n\n" if sections else ""
            header = f"File: {relative}\n"
            overhead = len(separator) + len(header)
            if overhead >= remaining:
                break
            content = result["content"][: remaining - overhead]
            sections.append(f"{header}{content}")
            remaining -= overhead + len(content)
        return "\n\n".join(sections)

    def _safe_relative_path(self, value: str) -> str | None:
        normalized = value.replace("\\", "/")
        path = Path(normalized)
        if path.is_absolute() or ".." in path.parts:
            return None
        relative = normalized.lstrip("./")
        return relative if relative and not relative.startswith("/") else None

    async def _restore_original_file(self, *, file_path: str, existed: bool, content: str) -> None:
        if existed:
            await self._tool("write_file", path=file_path, content=content)
            return
        relative = self._safe_relative_path(file_path)
        if relative is None:
            return
        target_path = self._project_root / relative
        if target_path.exists() or target_path.is_symlink():
            target_path.unlink()

    def _build_prompt(self, *, task: str, file_path: str, current_content: str, test_output: str, repository_context: str = "") -> str:
        prompt = f"Task:\n{task}\n\nTarget file:\n{file_path}\n\nCurrent content:\n{current_content}\n"
        if repository_context:
            prompt += "\nRelevant repository context (reference only; do not replace the task or target file):\n" + repository_context + "\n"
        if test_output:
            prompt += "\nPrevious test execution failed.\nTest output:\n" + test_output + "\n"
        return prompt + '\nReturn only valid JSON with this structure:\n{"content": "complete file content"}'
