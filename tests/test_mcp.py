import json
from typing import Any

import pytest

from mcp.client import Client
from mcp.server import MCPServer


SECRET = "v6-test-secret-do-not-disclose"


@pytest.fixture
def server() -> MCPServer:
    server = MCPServer("deterministic-v6")

    @server.tool()
    async def add(left: int, right: int) -> dict[str, int]:
        """Add two integers."""
        return {"sum": left + right}

    @server.tool()
    async def echo(value: str) -> dict[str, str]:
        """Return a supplied value."""
        return {"value": value}

    @server.tool()
    async def fail() -> None:
        """Raise a deliberately sanitized tool error."""
        raise RuntimeError("tool execution failed")

    @server.tool()
    async def secret_failure() -> None:
        """Raise an error containing a secret that must not escape."""
        raise RuntimeError(f"internal failure: {SECRET}")

    return server


def _text(result: Any) -> str:
    return "\n".join(
        item.text
        for item in result.content
        if getattr(item, "text", None) is not None
    )


async def _call(
    server: MCPServer,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    async with Client(server) as client:
        return await client.call_tool(name, arguments or {})


@pytest.mark.asyncio
async def test_server_creation_uses_official_mcp_server(server: MCPServer) -> None:
    assert isinstance(server, MCPServer)
    assert server.name == "deterministic-v6"


@pytest.mark.asyncio
async def test_discovery_is_deterministic(server: MCPServer) -> None:
    async with Client(server) as client:
        first = await client.list_tools()
        second = await client.list_tools()

    first_names = [tool.name for tool in first.tools]
    second_names = [tool.name for tool in second.tools]

    assert first_names == ["add", "echo", "fail", "secret_failure"]
    assert second_names == first_names
    assert first_names == sorted(first_names)


@pytest.mark.asyncio
async def test_successful_execution(server: MCPServer) -> None:
    result = await _call(server, "add", {"left": 20, "right": 22})

    assert not result.is_error
    assert json.loads(_text(result)) == {"sum": 42}


@pytest.mark.asyncio
async def test_unknown_tool_returns_an_error_without_executing_another_tool(
    server: MCPServer,
) -> None:
    result = await _call(server, "not_registered")

    assert result.is_error
    assert "not_registered" in _text(result)

    result = await _call(server, "echo", {"value": "still available"})
    assert not result.is_error
    assert json.loads(_text(result)) == {"value": "still available"}


@pytest.mark.asyncio
async def test_failing_tool_returns_a_sanitized_error_result(
    server: MCPServer,
) -> None:
    result = await _call(server, "fail")

    assert result.is_error
    error_text = _text(result)
    assert "Error executing tool fail" in error_text
    assert "tool execution failed" not in error_text


@pytest.mark.asyncio
async def test_errors_do_not_disclose_secrets(server: MCPServer) -> None:
    result = await _call(server, "secret_failure")

    assert result.is_error
    error_text = _text(result)
    assert SECRET not in error_text
    assert "internal failure" not in error_text


@pytest.mark.asyncio
async def test_registry_isolation_between_servers() -> None:
    first = MCPServer("first")
    second = MCPServer("second")

    @first.tool()
    async def only_first() -> dict[str, bool]:
        return {"first": True}

    async with Client(first) as first_client, Client(second) as second_client:
        first_tools = await first_client.list_tools()
        second_tools = await second_client.list_tools()

    assert [tool.name for tool in first_tools.tools] == ["only_first"]
    assert second_tools.tools == []


@pytest.mark.asyncio
async def test_client_discovery_and_calls_use_in_process_transport(
    server: MCPServer,
) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
        result = await client.call_tool("echo", {"value": "in-process"})

    assert [tool.name for tool in tools.tools] == [
        "add",
        "echo",
        "fail",
        "secret_failure",
    ]
    assert not result.is_error
    assert json.loads(_text(result)) == {"value": "in-process"}


@pytest.mark.asyncio
async def test_tool_results_are_json_serializable(server: MCPServer) -> None:
    result = await _call(server, "add", {"left": 1, "right": 2})
    value = json.loads(_text(result))

    assert json.dumps(value, sort_keys=True) == '{"sum": 3}'


@pytest.mark.asyncio
async def test_server_has_no_arbitrary_shell_capability(server: MCPServer) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()

    names = {tool.name for tool in tools.tools}
    assert not names.intersection(
        {
            "shell",
            "execute_shell",
            "run_command",
            "exec",
            "subprocess",
        }
    )
