import pytest

from app.agents.test_agent import TestAgent


@pytest.mark.asyncio
async def test_test_agent_detects_tests_and_asserts() -> None:
    agent = TestAgent()

    result = await agent.execute(
        {
            "project_name": "devpilot-ai",
            "source_code": (
                "def test_sum():\n"
                "    result = 1 + 1\n"
                "    assert result == 2\n"
            ),
        }
    )

    assert result["agent"] == "test_agent"
    assert result["project_name"] == "devpilot-ai"
    assert result["score"] == 100
    assert result["issues"] == []
    assert "1 test function(s)" in result["summary"]
    assert "1 assert statement(s)" in result["summary"]


@pytest.mark.asyncio
async def test_test_agent_warns_when_no_tests_exist() -> None:
    agent = TestAgent()

    result = await agent.execute(
        {
            "project_name": "devpilot-ai",
            "source_code": "def add(a, b):\n    return a + b\n",
        }
    )

    assert result["agent"] == "test_agent"
    assert result["score"] == 75
    assert len(result["issues"]) == 1
    assert result["issues"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_test_agent_detects_invalid_syntax() -> None:
    agent = TestAgent()

    result = await agent.execute(
        {
            "project_name": "broken-tests",
            "source_code": "def test_example(\n    assert True",
        }
    )

    assert result["agent"] == "test_agent"
    assert result["score"] == 0
    assert result["issues"][0]["severity"] == "critical"