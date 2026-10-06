import pytest

from app.agents.code_agent import CodeAgent


@pytest.mark.asyncio
async def test_code_agent_analyzes_valid_python_code() -> None:
    agent = CodeAgent()

    result = await agent.execute(
        {
            "project_name": "test-project",
            "source_code": (
                "class Calculator:\n"
                "    def add(self, a, b):\n"
                "        return a + b\n"
            ),
        }
    )

    assert result["agent"] == "code_agent"
    assert result["project_name"] == "test-project"
    assert result["score"] == 100
    assert result["issues"] == []
    assert "1 function(s)" in result["summary"]
    assert "1 class(es)" in result["summary"]


@pytest.mark.asyncio
async def test_code_agent_detects_invalid_python_syntax() -> None:
    agent = CodeAgent()

    result = await agent.execute(
        {
            "project_name": "broken-project",
            "source_code": "def hello(\n    return 'error'",
        }
    )

    assert result["agent"] == "code_agent"
    assert result["project_name"] == "broken-project"
    assert result["score"] == 0
    assert len(result["issues"]) == 1
    assert result["issues"][0]["severity"] == "critical"
    assert result["summary"] == "Python syntax error detected."