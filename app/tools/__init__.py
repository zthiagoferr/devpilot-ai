"""Public runtime API for the application tool system.

The package exposes runtime classes and factories, but never owns a mutable
registry instance.  Callers receive all runtime state explicitly, which keeps
separate application contexts isolated from one another.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar


_MISSING = object()


def _symbol(name: str, modules: Iterable[str]) -> Any:
    """Return the first available public symbol from the supported layouts."""
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        value = getattr(module, name, _MISSING)
        if value is not _MISSING:
            return value
    raise ImportError(f"Unable to import app.tools symbol {name!r}")


def _optional_symbol(name: str, modules: Iterable[str]) -> Any:
    try:
        return _symbol(name, modules)
    except ImportError:
        return None


class _FallbackTool:
    """Small compatibility base used by installations without V5 modules."""

    name = "tool"

    def __init__(self, name: str | None = None, **_: Any) -> None:
        if name is not None:
            self.name = name

    async def execute(self, **_: Any) -> Any:
        raise NotImplementedError


class _FallbackToolRegistry:
    """Instance-owned registry compatible with the common registry APIs."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def register(self, *args: Any) -> Any:
        if len(args) == 1:
            tool = args[0]
            name = getattr(tool, "name", tool.__class__.__name__)
        elif len(args) == 2:
            name, tool = args
        else:
            raise TypeError("register expects a tool or a name and tool")
        self.tools[str(name)] = tool
        return tool

    register_tool = register

    def get(self, name: str) -> Any:
        return self.tools[name]

    def get_tool(self, name: str) -> Any:
        return self.get(name)

    def list_tools(self) -> list[Any]:
        return list(self.tools.values())


class _FallbackToolExecutor:
    def __init__(self, registry: Any, **_: Any) -> None:
        self.registry = registry

    async def execute(self, tool: str | Any, **kwargs: Any) -> Any:
        instance = self.registry.get(tool) if isinstance(tool, str) else tool
        result = instance.execute(**kwargs)
        return await result if inspect.isawaitable(result) else result


class _FallbackSkill:
    name = "skill"


class _FallbackSkillRegistry:
    def __init__(self) -> None:
        self.skills: dict[str, Any] = {}

    def register(self, *args: Any) -> Any:
        if len(args) == 1:
            skill = args[0]
            name = getattr(skill, "name", skill.__class__.__name__)
        elif len(args) == 2:
            name, skill = args
        else:
            raise TypeError("register expects a skill or a name and skill")
        self.skills[str(name)] = skill
        return skill

    register_skill = register


Tool = _optional_symbol("Tool", ("app.tools.base", "app.tools.tool", "app.tools.core"))
Tool = Tool or _FallbackTool
ToolRegistry = _optional_symbol("ToolRegistry", ("app.tools.base", "app.tools.registry", "app.tools.core"))
ToolRegistry = ToolRegistry or _FallbackToolRegistry
ToolExecutor = _optional_symbol("ToolExecutor", ("app.tools.base", "app.tools.executor", "app.tools.core"))
ToolExecutor = ToolExecutor or _FallbackToolExecutor
Skill = _optional_symbol("Skill", ("app.tools.skill", "app.tools.skills", "app.tools.base"))
Skill = Skill or _FallbackSkill
SkillRegistry = _optional_symbol(
    "SkillRegistry", ("app.tools.base", "app.tools.skill", "app.tools.skills", "app.tools.registry")
)
SkillRegistry = SkillRegistry or _FallbackSkillRegistry


_result_modules = (
    "app.tools.result",
    "app.tools.results",
    "app.tools.types",
    "app.tools.base",
)
_error_modules = (
    "app.tools.error",
    "app.tools.errors",
    "app.tools.types",
    "app.tools.base",
)


@dataclass
class _FallbackToolResult:
    status: str = "success"
    value: Any = None
    error: Any = None


class _FallbackToolError(Exception):
    def __init__(self, message: str = "Tool execution failed", **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


ToolResult = _optional_symbol("ToolResult", _result_modules)
ToolResult = ToolResult or _optional_symbol("ToolExecutionResult", _result_modules)
ToolResult = ToolResult or _FallbackToolResult
ToolError = _optional_symbol("ToolError", _error_modules)
ToolError = ToolError or _optional_symbol("ToolExecutionError", _error_modules)
ToolError = ToolError or _FallbackToolError
ToolExecutionResult = _optional_symbol("ToolExecutionResult", _result_modules) or ToolResult
ToolExecutionError = _optional_symbol("ToolExecutionError", _error_modules) or ToolError


_ToolClass = TypeVar("_ToolClass")


def _make_tool(tool_class: type[_ToolClass], project_root: Path) -> _ToolClass:
    """Construct a project tool using its supported injected-root spelling."""
    try:
        return tool_class(project_root=project_root)
    except TypeError as first_error:
        try:
            return tool_class(root=project_root)
        except TypeError:
            raise first_error


def _add_tool(registry: Any, tool: Any) -> None:
    register = getattr(registry, "register", None) or getattr(registry, "register_tool", None)
    if register is None:
        raise TypeError("The supplied registry does not support tool registration")

    try:
        parameters = list(inspect.signature(register).parameters.values())
        positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        positional = []

    if len(positional) >= 2:
        register(tool.name, tool)
    else:
        register(tool)


def create_default_project_registry(
    project_root: str | Path,
    *,
    registry_factory: Callable[[], Any] = ToolRegistry,
) -> Any:
    """Create a fresh registry containing only the safe filesystem tools."""
    root = Path(project_root).expanduser().resolve()
    registry = registry_factory()

    from app.tools.filesystem import ListFilesTool, ReadFileTool, WriteFileTool

    for tool_class in (ListFilesTool, ReadFileTool, WriteFileTool):
        _add_tool(registry, _make_tool(tool_class, root))
    return registry


create_default_registry = create_default_project_registry
create_project_registry = create_default_project_registry
get_default_registry = create_default_project_registry


__all__ = [
    "Tool", "ToolRegistry", "ToolExecutor", "Skill", "SkillRegistry",
    "ToolResult", "ToolError", "ToolExecutionResult", "ToolExecutionError",
    "create_default_project_registry", "create_default_registry",
    "create_project_registry", "get_default_registry",
]
