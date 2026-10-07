from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.agents.base import BaseAgent
from app.agents.coding_agent import CodingAgent


_PROTECTED_NAMES = {".env", ".git", ".venv"}


@dataclass
class _Snapshot:
    path: Path
    existed: bool
    content: bytes | None = None
    mode: int | None = None


class DevelopmentAgent(BaseAgent):
    """Coordinate sequential file changes and roll them back on failure."""

    def __init__(
        self,
        coding_agent: CodingAgent | None = None,
        project_root: str | Path | None = None,
        llm_service: Any | None = None,
        tool_runtime: Any | None = None,
        v5_tool_runtime: Any | None = None,
    ) -> None:
        super().__init__(
            name="development_agent",
            responsibility=(
                "Coordinate multi-file development tasks through CodingAgent."
            ),
        )

        configured_root = project_root
        if configured_root is None and coding_agent is not None:
            configured_root = getattr(coding_agent, "project_root", None)
        self.project_root = (
            Path(configured_root).expanduser().resolve()
            if configured_root is not None
            else None
        )

        # ``v5_tool_runtime`` is retained as an explicit alias for callers using
        # the V5 naming convention.  The runtime is injected into CodingAgent
        # contexts; this agent does not execute arbitrary runtime operations.
        self.tool_runtime = (
            tool_runtime if tool_runtime is not None else v5_tool_runtime
        )

        self.coding_agent = coding_agent
        if self.coding_agent is None and self.project_root is not None:
            kwargs: dict[str, Any] = {
                "llm_service": llm_service,
                "project_root": self.project_root,
            }
            if self.tool_runtime is not None:
                kwargs["tool_runtime"] = self.tool_runtime
            try:
                self.coding_agent = CodingAgent(**kwargs)
            except TypeError:
                # Older CodingAgent implementations do not accept the injected
                # runtime.  Keep constructor compatibility and inject it below.
                kwargs.pop("tool_runtime", None)
                self.coding_agent = CodingAgent(**kwargs)

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        goal = context.get("development_goal", context.get("goal"))
        raw_tasks = context.get("file_tasks")
        if not isinstance(goal, str) or not goal.strip():
            return self._error("A non-empty development_goal is required.")
        if not isinstance(raw_tasks, list):
            return self._error("file_tasks must be a list.")
        if self.project_root is None:
            root = context.get("project_root")
            if root is not None:
                self.project_root = Path(root).expanduser().resolve()
        if self.project_root is None or not self.project_root.is_dir():
            return self._error("A valid project_root is required.")
        if self.coding_agent is None:
            return self._error("A CodingAgent is required.")

        runtime = context.get("tool_runtime")
        if runtime is None:
            runtime = context.get("v5_tool_runtime", self.tool_runtime)

        tasks: list[dict[str, str]] = []
        paths: list[Path] = []
        seen: set[Path] = set()
        for index, item in enumerate(raw_tasks):
            if not isinstance(item, Mapping):
                return self._error(f"file_tasks[{index}] must be an object.")
            file_path = item.get("file_path")
            task = item.get("task")
            if not isinstance(file_path, str) or not file_path.strip():
                return self._error(f"file_tasks[{index}] has an invalid file_path.")
            if not isinstance(task, str) or not task.strip():
                return self._error(f"file_tasks[{index}] has an invalid task.")
            try:
                path = self._safe_path(file_path)
            except ValueError as exc:
                return self._error(str(exc))
            tasks.append({"file_path": file_path, "task": task})
            if path not in seen:
                seen.add(path)
                paths.append(path)

        snapshots: list[_Snapshot] = []
        try:
            for path in paths:
                snapshots.append(self._snapshot(path))
        except (OSError, ValueError) as exc:
            return self._error(f"Unable to snapshot target files: {exc}")

        completed_tasks: list[dict[str, str]] = []
        task_results: list[dict[str, Any]] = []
        for index, item in enumerate(tasks):
            coding_context: dict[str, Any] = {
                "development_goal": goal,
                "task": item["task"],
                "file_path": item["file_path"],
            }
            if runtime is not None:
                coding_context["tool_runtime"] = runtime
                coding_context["v5_tool_runtime"] = runtime
            try:
                result = await self.coding_agent.execute(coding_context)
            except Exception as exc:
                failure_result: dict[str, Any] = {
                    "status": "error",
                    "message": str(exc),
                }
                rollback_errors = self._rollback(snapshots)
                return self._failure(
                    goal,
                    completed_tasks,
                    task_results,
                    index,
                    item,
                    failure_result,
                    rollback_errors,
                )

            if not isinstance(result, dict):
                result = {"status": "error", "message": "Invalid CodingAgent result."}
            task_results.append(result)
            if result.get("status") != "completed":
                rollback_errors = self._rollback(snapshots)
                return self._failure(
                    goal,
                    completed_tasks,
                    task_results,
                    index,
                    item,
                    result,
                    rollback_errors,
                )
            completed_tasks.append(item)

        return {
            "agent": self.name,
            "status": "completed",
            "development_goal": goal,
            "completed_tasks": completed_tasks,
            "task_results": task_results,
            "failure": None,
        }

    def _safe_path(self, file_path: str) -> Path:
        if self.project_root is None:
            raise ValueError("A valid project_root is required.")
        relative = Path(file_path)
        if relative.is_absolute():
            raise ValueError("file_path must be relative to project_root.")
        if any(part in _PROTECTED_NAMES for part in relative.parts):
            raise ValueError("Access to protected project paths is forbidden.")
        path = (self.project_root / relative).resolve(strict=False)
        try:
            path.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("file_path must remain inside project_root.") from exc
        return path

    def _snapshot(self, path: Path) -> _Snapshot:
        if path.is_symlink():
            raise ValueError(f"Refusing to access symlink target: {path.name}")
        if not path.exists():
            return _Snapshot(path=path, existed=False)
        if not path.is_file():
            raise ValueError(f"Target is not a regular file: {path.name}")
        stat = path.stat()
        return _Snapshot(
            path=path,
            existed=True,
            content=path.read_bytes(),
            mode=stat.st_mode,
        )

    def _rollback(self, snapshots: list[_Snapshot]) -> list[str]:
        errors: list[str] = []
        for snapshot in snapshots:
            try:
                path = snapshot.path
                if snapshot.existed:
                    if path.is_symlink():
                        path.unlink()
                    elif path.exists() and not path.is_file():
                        raise OSError("target became a non-file")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(snapshot.content or b"")
                    if snapshot.mode is not None:
                        path.chmod(snapshot.mode)
                elif path.exists() or path.is_symlink():
                    if path.is_dir() and not path.is_symlink():
                        raise OSError("created target is a directory")
                    path.unlink()
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        return errors

    def _error(self, message: str) -> dict[str, Any]:
        return {"agent": self.name, "status": "error", "message": message}

    def _failure(
        self,
        goal: str,
        completed: list[dict[str, str]],
        results: list[dict[str, Any]],
        index: int,
        task: dict[str, str],
        result: dict[str, Any],
        rollback_errors: list[str],
    ) -> dict[str, Any]:
        failure: dict[str, Any] = {
            "task_index": index,
            "task": task,
            "result": result,
        }
        if rollback_errors:
            failure["rollback_errors"] = rollback_errors
        return {
            "agent": self.name,
            "status": "failed",
            "development_goal": goal,
            "completed_tasks": completed,
            "task_results": results,
            "failure": failure,
        }
