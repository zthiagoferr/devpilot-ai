import pytest

from app.agents.orchestrator import OrchestratorAgent


@pytest.mark.asyncio
async def test_orchestrator_delegates_code_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "code",
            "project_name": "devpilot-ai",
            "source_code": (
                "class UserService:\n"
                "    def get_user(self):\n"
                "        return {'id': 1}\n"
            ),
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == "code_agent"

    code_result = result["result"]

    assert code_result["agent"] == "code_agent"
    assert code_result["project_name"] == "devpilot-ai"
    assert code_result["score"] == 100
    assert code_result["issues"] == []


@pytest.mark.asyncio
async def test_orchestrator_rejects_unknown_task() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "security",
            "project_name": "devpilot-ai",
            "source_code": "print('hello')",
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "error"
    assert result["message"] == "No agent available for task: security"


@pytest.mark.asyncio
async def test_orchestrator_rejects_missing_task() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "project_name": "devpilot-ai",
            "source_code": "print('hello')",
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "error"
    assert result["message"] == "Task was not provided."

@pytest.mark.asyncio
async def test_orchestrator_delegates_test_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "tests",
            "project_name": "devpilot-ai",
            "source_code": (
                "def test_health():\n"
                "    assert True\n"
            ),
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == "test_agent"
    assert result["result"]["agent"] == "test_agent"
    assert result["result"]["score"] == 100

@pytest.mark.asyncio
async def test_orchestrator_delegates_docs_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "docs",
            "project_name": "devpilot-ai",
            "source_code": (
                "def health_check():\n"
                '    """Return application health status."""\n'
                "    return {'status': 'healthy'}\n"
            ),
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == "docs_agent"
    assert result["result"]["agent"] == "docs_agent"
    assert result["result"]["score"] == 100