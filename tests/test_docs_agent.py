import pytest

from app.agents.docs_agent import DocsAgent


@pytest.mark.asyncio
async def test_docs_agent_detects_documented_code() -> None:
    agent = DocsAgent()

    result = await agent.execute(
        {
            "project_name": "devpilot-ai",
            "source_code": (
                "class UserService:\n"
                '    """Handles user operations."""\n'
                "\n"
                "    def get_user(self):\n"
                '        """Return a user."""\n'
                "        return {'id': 1}\n"
            ),
        }
    )

    assert result["agent"] == "docs_agent"
    assert result["score"] == 100
    assert result["issues"] == []
    assert "2 documentable object(s)" in result["summary"]
    assert "2 documented" in result["summary"]


@pytest.mark.asyncio
async def test_docs_agent_detects_missing_docstrings() -> None:
    agent = DocsAgent()

    result = await agent.execute(
        {
            "project_name": "devpilot-ai",
            "source_code": (
                "class UserService:\n"
                "    def get_user(self):\n"
                "        return {'id': 1}\n"
            ),
        }
    )

    assert result["agent"] == "docs_agent"
    assert result["score"] == 0
    assert len(result["issues"]) == 1
    assert result["issues"][0]["severity"] == "warning"


@pytest.mark.asyncio
async def test_docs_agent_detects_invalid_syntax() -> None:
    agent = DocsAgent()

    result = await agent.execute(
        {
            "project_name": "broken-project",
            "source_code": "def broken(\n    return True",
        }
    )

    assert result["agent"] == "docs_agent"
    assert result["score"] == 0
    assert result["issues"][0]["severity"] == "critical"
