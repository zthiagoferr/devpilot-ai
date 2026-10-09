"""Transport-independent MCP integration for explicitly registered DevPilot tools.

The server is built from the canonical :class:`app.tools.ToolRegistry`.  Each
registry tool is registered on the official MCP SDK ``MCPServer`` with an input
schema derived from the tool's own JSON schema, and calls are delegated to
``ToolExecutor`` so its sanitized failure semantics remain the single source of
truth for tool execution.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from mcp.server import MCPServer

from app.tools import ToolExecutor, ToolRegistry


_SERVER_NAME = "devpilot"

_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _build_signature(input_schema: Mapping[str, Any]) -> inspect.Signature:
    """Build a keyword-only signature from a tool's JSON input schema.

    The MCP SDK derives the advertised input schema from the handler's
    signature, so this preserves the reviewed parameter names and required
    flags instead of exposing a generic ``**kwargs`` tool.
    """
    properties = input_schema.get("properties")
    if not isinstance(properties, Mapping):
        properties = {}
    required = input_schema.get("required")
    required_names = set(required) if isinstance(required, (list, tuple)) else set()

    parameters: list[inspect.Parameter] = []
    for name, specification in properties.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError(f"Tool schema contains an invalid parameter name: {name!r}")
        spec = specification if isinstance(specification, Mapping) else {}
        annotation = _TYPE_MAP.get(spec.get("type"), Any)
        default = (
            inspect.Parameter.empty if name in required_names else None
        )
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )
    return inspect.Signature(parameters)


def create_mcp_server(tool_registry: ToolRegistry) -> MCPServer:
    """Create an MCP server backed by the supplied canonical tool registry."""
    if not isinstance(tool_registry, ToolRegistry):
        raise TypeError("tool_registry must be a ToolRegistry.")

    executor = ToolExecutor(tool_registry)
    server = MCPServer(_SERVER_NAME)

    for metadata in tool_registry.discovery_metadata():
        name = metadata["name"]
        description = metadata.get("description", "")
        schema = metadata.get("input_schema") or {"type": "object", "properties": {}}

        def make_handler(tool_name: str):
            async def handler(**kwargs: Any) -> dict[str, Any]:
                execution = await executor.execute(tool_name, **kwargs)
                return execution.to_dict()

            return handler

        handler = make_handler(name)
        handler.__name__ = name
        handler.__signature__ = _build_signature(schema)  # type: ignore[attr-defined]
        server.add_tool(handler, name=name, description=description)

    return server
