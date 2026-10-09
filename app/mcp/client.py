"""Dependency-injected, in-process MCP client abstraction.

The class in this module deliberately does not know how an MCP server is
transported.  An MCP SDK ``Client`` instance may be supplied directly, or a
server may be supplied and used to construct the official SDK client lazily.
This keeps the abstraction suitable for tests and for in-process
``MCPServer`` instances without introducing ports, subprocesses, or global
state.
"""

from __future__ import annotations

import inspect
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Callable, Mapping


class MCPClient:
    """Small, deterministic wrapper around the MCP SDK v2 ``Client`` API.

    Parameters are intentionally injectable.  In production, pass an MCP
    server and let this class construct ``mcp.Client``.  Tests and embedded
    applications can pass ``client`` (or ``client_factory``) instead.
    """

    def __init__(
        self,
        server: Any | None = None,
        *,
        client: Any | None = None,
        mcp_client: Any | None = None,
        client_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        if client is not None and mcp_client is not None:
            raise TypeError("provide only one of client and mcp_client")
        if client is not None:
            mcp_client = client
        if mcp_client is not None and client_factory is not None:
            raise TypeError("provide a client or a client_factory, not both")
        if mcp_client is None and server is None:
            raise TypeError("an MCP server or client is required")

        self.server = server
        self._client = mcp_client
        self._client_factory = client_factory
        self._initialized = False
        self._closed = False

    @property
    def client(self) -> Any:
        """Return the underlying SDK client, constructing it if necessary."""
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory(self.server)
            else:
                try:
                    from mcp import Client  # type: ignore[import-not-found]
                except (ImportError, AttributeError) as exc:
                    raise RuntimeError("The MCP SDK Client is unavailable.") from exc
                self._client = Client(self.server)
        return self._client

    @staticmethod
    def _jsonable(value: Any) -> Any:
        """Convert SDK response objects into strictly JSON-compatible data."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Enum):
            return MCPClient._jsonable(value.value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, Mapping):
            return {
                str(key): MCPClient._jsonable(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            return [MCPClient._jsonable(item) for item in value]
        if is_dataclass(value) and not isinstance(value, type):
            return MCPClient._jsonable(asdict(value))

        for method_name in ("model_dump", "dict"):
            method = getattr(value, method_name, None)
            if callable(method):
                try:
                    dumped = method(mode="json") if method_name == "model_dump" else method()
                except TypeError:
                    dumped = method()
                return MCPClient._jsonable(dumped)

        if hasattr(value, "__dict__"):
            return MCPClient._jsonable(
                {
                    key: item
                    for key, item in vars(value).items()
                    if not key.startswith("_")
                }
            )
        return str(value)

    @staticmethod
    def _field(value: Any, *names: str, default: Any = None) -> Any:
        for name in names:
            if isinstance(value, Mapping) and name in value:
                return value[name]
            if hasattr(value, name):
                return getattr(value, name)
        return default

    @classmethod
    def _tool_definition(cls, tool: Any) -> dict[str, Any]:
        name = cls._field(tool, "name", default="")
        description = cls._field(tool, "description", default="")
        schema = cls._field(tool, "inputSchema", "input_schema", "schema", default={})
        return {
            "name": str(name),
            "description": "" if description is None else str(description),
            "input_schema": cls._jsonable(schema or {}),
        }

    @classmethod
    def _tools_from_response(cls, response: Any) -> list[Any]:
        if isinstance(response, Mapping):
            return list(response.get("tools", []))
        tools = getattr(response, "tools", None)
        if tools is not None:
            return list(tools)
        if isinstance(response, (list, tuple)):
            return list(response)
        return []

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"status": "error", "error": {"code": code, "message": message}}

    async def _ensure_initialized(self) -> None:
        if self._closed:
            raise RuntimeError("The MCP client is closed.")
        if self._initialized:
            return
        client = self.client
        # The official SDK ``Client`` connects through its async context
        # manager; entering it establishes the in-process transport.
        enter = getattr(client, "__aenter__", None)
        if callable(enter):
            await enter()
        self._initialized = True

    async def discover_tools(self) -> list[dict[str, Any]] | dict[str, Any]:
        """Discover tools and return stable, SDK-independent definitions."""
        try:
            await self._ensure_initialized()
            response = self.client.list_tools()
            if inspect.isawaitable(response):
                response = await response
            definitions = [self._tool_definition(tool) for tool in self._tools_from_response(response)]
            definitions.sort(key=lambda item: item["name"])
            return definitions
        except Exception:
            return self._error("discovery_error", "Unable to discover MCP tools.")

    async def list_tools(self) -> list[dict[str, Any]] | dict[str, Any]:
        """Alias matching the SDK operation name."""
        return await self.discover_tools()

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any:
        """Call one tool with structured arguments and a JSON-safe result."""
        if not isinstance(name, str) or not name:
            return self._error("invalid_input", "The tool name must be a non-empty string.")
        if arguments is not None and not isinstance(arguments, Mapping):
            return self._error("invalid_input", "Tool arguments must be an object.")
        args = dict(arguments or {})
        try:
            await self._ensure_initialized()
            result = self.client.call_tool(name=name, arguments=args)
            if inspect.isawaitable(result):
                result = await result
            return self._jsonable(result)
        except Exception:
            return self._error("call_error", "Unable to execute the MCP tool.")

    async def close(self) -> None:
        if self._client is None or self._closed:
            self._closed = True
            return
        if self._initialized:
            exit_ = getattr(self.client, "__aexit__", None)
            if callable(exit_):
                result = exit_(None, None, None)
                if inspect.isawaitable(result):
                    await result
        self._closed = True

    async def __aenter__(self) -> "MCPClient":
        await self._ensure_initialized()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()


V6MCPClient = MCPClient

__all__ = ["MCPClient", "V6MCPClient"]
