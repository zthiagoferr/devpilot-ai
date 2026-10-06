import pytest
from app.agents.insights_agent import InsightsAgent
from app.llm.fake import FakeLLMProvider
from app.services.llm_service import LLMService
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

@pytest.mark.asyncio
async def test_orchestrator_runs_full_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "full_analysis",
            "project_name": "devpilot-ai",
            "source_code": (
                "def test_health():\n"
                '    """Test application health."""\n'
                "    assert True\n"
            ),
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"

    assert result["delegated_to"] == [
        "code_agent",
        "test_agent",
        "docs_agent",
        "report_agent",
    ]

    report = result["result"]["report"]

    assert report["agent"] == "report_agent"
    assert report["project_name"] == "devpilot-ai"
    assert report["overall_score"] == 100
    assert report["total_issues"] == 0

    assert "code" in report["analyses"]
    assert "tests" in report["analyses"]
    assert "docs" in report["analyses"]

@pytest.mark.asyncio
async def test_orchestrator_runs_full_analysis_with_insights() -> None:
    provider = FakeLLMProvider(
        response="Improve test coverage and documentation.",
        model="fake-model",
    )
    service = LLMService(provider)
    insights_agent = InsightsAgent(service)

    orchestrator = OrchestratorAgent(
        insights_agent=insights_agent,
    )

    result = await orchestrator.execute(
        {
            "task": "full_analysis",
            "project_name": "devpilot-ai",
            "source_code": (
                "def test_health():\n"
                '    """Test application health."""\n'
                "    assert True\n"
            ),
        }
    )

    assert result["status"] == "completed"

    assert result["delegated_to"] == [
        "code_agent",
        "test_agent",
        "docs_agent",
        "report_agent",
        "insights",
    ]

    assert "report" in result["result"]
    assert "insights" in result["result"]

    insights = result["result"]["insights"]

    assert insights["agent"] == "insights"
    assert insights["status"] == "completed"
    assert insights["model"] == "fake-model"
    assert (
        insights["recommendations"]
        == "Improve test coverage and documentation."
    )

    assert provider.last_prompt is not None
    assert "devpilot-ai" in provider.last_prompt