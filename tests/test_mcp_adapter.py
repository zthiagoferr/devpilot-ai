"""Integration tests for the MCP adapter over the canonical tool registry.

These use the real ``mcp`` SDK (``MCPServer`` / ``Client``) through the project's
``create_mcp_server`` and ``MCPClient`` wrappers.
"""

from typing import Any

import pytest

from app.mcp import MCPClient, create_mcp_server
from app.tools import ToolRegistry
from app.tools.base import BaseTool


SECRET = "mcp-adapter-secret-do-not-disclose"


class _EchoTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            name="echo",
            description="Echo a value.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return {"value": kwargs["value"]}


class _FailingTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(name="failing", description="Always fails.")

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(f"internal failure: {SECRET}")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    registry.register(_FailingTool())
    return registry


def _text(result: dict[str, Any]) -> str:
    return result["content"][0]["text"]


@pytest.mark.asyncio
async def test_discovery_and_call_use_canonical_registry() -> None:
    server = create_mcp_server(_registry())

    async with MCPClient(server) as client:
        tools = await client.discover_tools()
        assert [tool["name"] for tool in tools] == ["echo", "failing"]

        result = await client.call_tool("echo", {"value": "hello"})
        assert result["is_error"] is False
        assert '"value": "hello"' in _text(result)


@pytest.mark.asyncio
async def test_failures_are_sanitized() -> None:
    server = create_mcp_server(_registry())

    async with MCPClient(server) as client:
        result = await client.call_tool("failing", {})

    assert SECRET not in _text(result)
    assert "internal failure" not in _text(result)


@pytest.mark.asyncio
async def test_unknown_tool_fails_closed() -> None:
    server = create_mcp_server(_registry())

    async with MCPClient(server) as client:
        result = await client.call_tool("not_registered", {})

    assert result["is_error"] is True
    assert "not_registered" in _text(result)


@pytest.mark.asyncio
async def test_servers_are_isolated() -> None:
    first = create_mcp_server(_registry())
    second = create_mcp_server(ToolRegistry())

    async with MCPClient(first) as first_client, MCPClient(second) as second_client:
        first_tools = await first_client.discover_tools()
        second_tools = await second_client.discover_tools()

    assert [tool["name"] for tool in first_tools] == ["echo", "failing"]
    assert second_tools == []
