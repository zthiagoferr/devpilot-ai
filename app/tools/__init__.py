"""Public runtime API for the application tool system.

The package re-exports the canonical runtime classes from :mod:`app.tools.base`
and provides explicit factories.  It never owns a mutable registry instance:
callers receive all runtime state explicitly, which keeps separate application
contexts isolated from one another.
"""

from __future__ import annotations

from pathlib import Path

from app.tools.base import (
    BaseTool,
    Skill,
    SkillRegistry,
    Tool,
    ToolExecutionError,
    ToolExecutionResult,
    ToolExecutor,
    ToolRegistry,
)

__all__ = [
    "BaseTool",
    "Skill",
    "SkillRegistry",
    "Tool",
    "ToolExecutionError",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolRegistry",
    "create_default_project_registry",
]


def create_default_project_registry(project_root: str | Path) -> ToolRegistry:
    """Create a fresh registry containing the safe filesystem tools."""
    from app.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool

    root = Path(project_root).expanduser().resolve()
    registry = ToolRegistry()
    for tool_class in (ListFilesTool, ReadFileTool, WriteFileTool):
        registry.register(tool_class(project_root=root))
    return registry
