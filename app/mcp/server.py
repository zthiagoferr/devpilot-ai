"""Transport-independent MCP integration for explicitly registered DevPilot tools."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from mcp.server import MCPServer
from mcp.types import TextContent, Tool

from app.tools import ToolExecutor, ToolRegistry


_SERVER_NAME = "devpilot"


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe value without exposing implementation details."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]
    return None


def _safe_json_text(value: Any) -> str:
    """Serialize a structured result without serializing arbitrary objects."""
    safe_value = _json_safe(value)
    try:
        return json.dumps(safe_value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError):
        return json.dumps(
            {"status": "failed", "error": "Tool result could not be serialized."},
            sort_keys=True,
            separators=(",", ":"),
        )


def _tool_metadata(registry: ToolRegistry) -> tuple[dict[str, Any], ...]:
    """Take an immutable, JSON-safe snapshot of the registry's tool metadata."""
    metadata: list[dict[str, Any]] = []
    for item in registry.discovery_metadata():
        if not isinstance(item, Mapping):
            continue

        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue

        description = item.get("description", "")
        if not isinstance(description, str):
            description = ""

        schema = item.get("input_schema", item.get("inputSchema"))
        if not isinstance(schema, Mapping):
            schema = {"type": "object", "properties": {}}

        safe_schema = _json_safe(deepcopy(dict(schema)))
        if not isinstance(safe_schema, dict):
            safe_schema = {"type": "object", "properties": {}}

        metadata.append(
            {
                "name": name,
                "description": description,
                "input_schema": safe_schema,
            }
        )

    metadata.sort(key=lambda item: item["name"])
    return tuple(metadata)


def create_mcp_server(tool_registry: ToolRegistry) -> MCPServer:
    """Create an MCP server backed by the supplied canonical tool registry.

    The registry is supplied by the application and is never replaced or
    mutated here.  The server exposes the tools present when it is created.
    Calls are delegated to ``ToolExecutor`` so its sanitized failure semantics
    remain the single source of truth for tool execution.
    """
    if not isinstance(tool_registry, ToolRegistry):
        raise TypeError("tool_registry must be a ToolRegistry.")

    metadata = _tool_metadata(tool_registry)
    exposed_names = frozenset(item["name"] for item in metadata)
    executor = ToolExecutor(tool_registry)
    server = MCPServer(_SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=item["name"],
                description=item["description"],
                inputSchema=item["input_schema"],
            )
            for item in metadata
        ]

    @server.call_tool()
    async def call_tool(
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> list[TextContent]:
        if not isinstance(name, str) or name not in exposed_names:
            result: dict[str, Any] = {
                "status": "failed",
                "error": "Tool is not registered.",
            }
        elif arguments is not None and not isinstance(arguments, dict):
            result = {
                "status": "failed",
                "error": "Invalid tool arguments.",
            }
        else:
            try:
                execution = await executor.execute(name, **(arguments or {}))
                result = execution.to_dict()
            except Exception:
                result = {
                    "status": "failed",
                    "error": "Tool execution failed.",
                }

        return [TextContent(type="text", text=_safe_json_text(result))]

    return server


# Explicit aliases provide descriptive construction names without creating a
# server or registry at import time.
def build_mcp_server(tool_registry: ToolRegistry) -> MCPServer:
    return create_mcp_server(tool_registry)


def create_server(tool_registry: ToolRegistry) -> MCPServer:
    return create_mcp_server(tool_registry)
