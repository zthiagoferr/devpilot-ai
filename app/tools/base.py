from __future__ import annotations

import copy
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, TypeAlias


JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)
JSONSchema: TypeAlias = dict[str, JSONValue]


class BaseTool(ABC):
    """Typed contract for tools available to DevPilot agents."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Mapping[str, Any] | None = None,
    ) -> None:
        self.name = self._required_text(name, "name")
        self.description = self._required_text(description, "description")

        schema: Mapping[str, Any] = input_schema or {
            "type": "object",
            "properties": {},
        }
        self.input_schema = self._json_schema(schema)

    @staticmethod
    def _required_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _json_schema(value: Mapping[str, Any]) -> JSONSchema:
        if not isinstance(value, Mapping):
            raise ValueError("input_schema must be a JSON object")
        try:
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
            decoded = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise ValueError("input_schema must be JSON serializable") from exc
        if not isinstance(decoded, dict):
            raise ValueError("input_schema must be a JSON object")
        return decoded

    def metadata(self) -> dict[str, JSONValue]:
        """Return stable, JSON-serializable tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": copy.deepcopy(self.input_schema),
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool and return a structured result."""
        raise NotImplementedError


# The alias keeps the short contract name available without breaking existing
# integrations that subclass BaseTool.
Tool = BaseTool


@dataclass(frozen=True)
class ToolExecutionResult:
    """A bounded result returned by the tool executor."""

    success: bool
    output: dict[str, JSONValue] | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        return "completed" if self.success else "failed"

    @property
    def data(self) -> dict[str, JSONValue] | None:
        return self.output

    def to_dict(self) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {"status": self.status}
        if self.success:
            if self.output is not None:
                result["output"] = copy.deepcopy(self.output)
        elif self.error is not None:
            result["error"] = self.error
        return result

    @classmethod
    def completed(cls, output: Mapping[str, Any] | None = None) -> ToolExecutionResult:
        if output is None:
            return cls(success=True, output={})
        return cls(success=True, output=_safe_json_object(output))

    @classmethod
    def failed(cls, message: str = "Tool execution failed.") -> ToolExecutionResult:
        return cls(success=False, error=_safe_error_message(message))


class ToolExecutionError(Exception):
    """Safe execution error which never carries exception implementation details."""

    def __init__(self, message: str = "Tool execution failed.") -> None:
        self.safe_message = _safe_error_message(message)
        super().__init__(self.safe_message)


def _safe_error_message(message: str) -> str:
    allowed = {
        "Tool execution failed.",
        "Tool is not registered.",
        "Tool returned an invalid result.",
        "Tool input is not JSON serializable.",
    }
    return message if message in allowed else "Tool execution failed."


def _safe_json_object(value: Mapping[str, Any]) -> dict[str, JSONValue]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ToolExecutionError("Tool returned an invalid result.") from None
    if not isinstance(decoded, dict):
        raise ToolExecutionError("Tool returned an invalid result.")
    return decoded


class ToolRegistry:
    """Explicit, process-local registry of approved tool instances."""

    def __init__(self, tools: Iterable[BaseTool] = ()) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        if not isinstance(tool, BaseTool):
            raise TypeError("tool must implement BaseTool")
        if tool.name in self._tools:
            raise ValueError(f"A tool named {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def lookup(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def get(self, name: str) -> BaseTool | None:
        return self.lookup(name)

    def discovery_metadata(self) -> list[dict[str, JSONValue]]:
        return [
            copy.deepcopy(self._tools[name].metadata())
            for name in sorted(self._tools)
        ]

    def metadata(self) -> list[dict[str, JSONValue]]:
        return self.discovery_metadata()


class ToolExecutor:
    """Executes tools only after resolving them from an explicit registry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, name: str, **kwargs: Any) -> ToolExecutionResult:
        tool = self._registry.lookup(name)
        if tool is None:
            return ToolExecutionResult.failed("Tool is not registered.")
        try:
            _safe_json_object(kwargs)
            value = await tool.execute(**kwargs)
            if isinstance(value, ToolExecutionResult):
                return value
            return ToolExecutionResult.completed(value)
        except ToolExecutionError as exc:
            return ToolExecutionResult.failed(exc.safe_message)
        except Exception:
            return ToolExecutionResult.failed()

    async def invoke(self, name: str, arguments: Mapping[str, Any] | None = None) -> ToolExecutionResult:
        return await self.execute(name, **dict(arguments or {}))


class Skill:
    """A named grouping of tool metadata for discovery and agent planning."""

    def __init__(
        self,
        name: str,
        description: str,
        tools: Iterable[BaseTool],
    ) -> None:
        self.name = BaseTool._required_text(name, "name")
        self.description = BaseTool._required_text(description, "description")
        tool_list = list(tools)
        if any(not isinstance(tool, BaseTool) for tool in tool_list):
            raise TypeError("skills may contain only BaseTool instances")
        names = [tool.name for tool in tool_list]
        if len(names) != len(set(names)):
            raise ValueError("a skill cannot contain duplicate tools")
        self.tools = tuple(sorted(tool_list, key=lambda tool: tool.name))

    def metadata(self) -> dict[str, JSONValue]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": [tool.metadata() for tool in self.tools],
        }


class SkillRegistry:
    """Explicit registry of skills with deterministic discovery output."""

    def __init__(self, skills: Iterable[Skill] = ()) -> None:
        self._skills: dict[str, Skill] = {}
        for skill in skills:
            self.register(skill)

    def register(self, skill: Skill) -> None:
        if not isinstance(skill, Skill):
            raise TypeError("skill must be a Skill")
        if skill.name in self._skills:
            raise ValueError(f"A skill named {skill.name!r} is already registered")
        self._skills[skill.name] = skill

    def lookup(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def get(self, name: str) -> Skill | None:
        return self.lookup(name)

    def discovery_metadata(self) -> list[dict[str, JSONValue]]:
        return [copy.deepcopy(self._skills[name].metadata()) for name in sorted(self._skills)]

    def metadata(self) -> list[dict[str, JSONValue]]:
        return self.discovery_metadata()
