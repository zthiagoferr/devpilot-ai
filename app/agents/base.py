from abc import ABC, abstractmethod
import inspect
from typing import Any

try:
    from app.tools.registry import ToolRegistry
except ImportError:  # pragma: no cover - compatibility for minimal installations
    class ToolRegistry:
        """Small fallback registry used when the tools package is unavailable."""

        def __init__(self) -> None:
            self._tools: dict[str, Any] = {}

        def register(self, name: str, tool: Any) -> None:
            self._tools[name] = tool

        def list_tools(self) -> list[str]:
            return list(self._tools)

        def get_tool(self, name: str) -> Any | None:
            return self._tools.get(name)

try:
    from app.tools.executor import ToolExecutor
except ImportError:  # pragma: no cover - compatibility for minimal installations
    class ToolExecutor:
        """Small fallback executor used when the tools package is unavailable."""

        def __init__(self, registry: ToolRegistry) -> None:
            self.registry = registry

        async def execute(
            self,
            name: str,
            arguments: dict[str, Any] | None = None,
        ) -> Any:
            tool = self.registry.get_tool(name)
            if tool is None:
                raise ValueError(f"Tool is not registered: {name}")
            result = tool(**(arguments or {}))
            if inspect.isawaitable(result):
                return await result
            return result


class BaseAgent(ABC):
    """Base contract for every specialized DevPilot AI agent."""

    def __init__(
        self,
        name: str,
        responsibility: str,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.name = name
        self.responsibility = responsibility

        # Defaults are created per agent.  In particular, no registry is shared
        # between agents, while callers can still supply either dependency.
        self.tool_registry = (
            tool_registry if tool_registry is not None else ToolRegistry()
        )
        self.tool_executor = (
            tool_executor
            if tool_executor is not None
            else ToolExecutor(self.tool_registry)
        )

    def discover_tools(self) -> list[str]:
        """Return registered tool names in deterministic order."""
        registry = self.tool_registry
        names: Any = None

        list_method = getattr(registry, "list_tools", None)
        if callable(list_method):
            names = list_method()
        elif isinstance(getattr(registry, "tools", None), dict):
            names = registry.tools.keys()
        elif isinstance(getattr(registry, "_tools", None), dict):
            names = registry._tools.keys()

        if names is None:
            return []
        if isinstance(names, dict):
            names = names.keys()

        result: list[str] = []
        for item in names:
            if isinstance(item, str):
                result.append(item)
            else:
                item_name = getattr(item, "name", None)
                if isinstance(item_name, str):
                    result.append(item_name)
        return sorted(set(result))

    def _is_tool_registered(self, name: str) -> bool:
        """Check registration without relying on a particular registry API."""
        if name in self.discover_tools():
            return True

        registry = self.tool_registry
        for method_name in ("has_tool", "contains"):
            method = getattr(registry, method_name, None)
            if callable(method):
                return bool(method(name))

        for method_name in ("get_tool", "get"):
            method = getattr(registry, method_name, None)
            if callable(method):
                return method(name) is not None

        for attribute in ("tools", "_tools"):
            tools = getattr(registry, attribute, None)
            if isinstance(tools, dict):
                return name in tools
        return False

    async def invoke_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke a registered tool, refusing unknown names before execution."""
        if not self._is_tool_registered(name):
            raise ValueError(f"Tool is not registered: {name}")

        params = dict(arguments or {})
        params.update(kwargs)
        executor = self.tool_executor
        method = getattr(executor, "execute", None)
        if not callable(method):
            method = getattr(executor, "invoke", None)
        if not callable(method):
            raise TypeError("Tool executor must provide execute() or invoke()")

        result = method(name, params)
        if inspect.isawaitable(result):
            return await result
        return result

    # These aliases keep the helpers convenient for specialized agents whose
    # terminology uses either "execute" or "run" for a tool invocation.
    async def execute_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return await self.invoke_tool(name, arguments, **kwargs)

    async def run_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return await self.invoke_tool(name, arguments, **kwargs)

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute only the responsibility assigned to this agent."""
        raise NotImplementedError
