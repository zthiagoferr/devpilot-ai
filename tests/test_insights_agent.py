import pytest

from app.agents.insights_agent import InsightsAgent
from app.llm.fake import FakeLLMProvider
from app.services.llm_service import LLMService


@pytest.mark.asyncio
async def test_insights_agent_generates_recommendations() -> None:
    provider = FakeLLMProvider(
        response="Add tests and improve documentation.",
        model="fake-model",
    )
    service = LLMService(provider)
    agent = InsightsAgent(service)

    report = {
        "project_name": "devpilot-ai",
        "overall_score": 80,
        "issues": [
            {
                "severity": "warning",
                "message": "Missing documentation.",
            }
        ],
    }

    result = await agent.execute(
        {
            "report": report,
        }
    )

    assert result == {
        "agent": "insights",
        "status": "completed",
        "model": "fake-model",
        "recommendations": "Add tests and improve documentation.",
    }

    assert provider.last_system_prompt is not None
    assert "senior Python software engineer" in provider.last_system_prompt

    assert provider.last_prompt is not None
    assert "devpilot-ai" in provider.last_prompt
    assert "Missing documentation." in provider.last_prompt


@pytest.mark.asyncio
async def test_insights_agent_rejects_missing_report() -> None:
    provider = FakeLLMProvider()
    service = LLMService(provider)
    agent = InsightsAgent(service)

    result = await agent.execute({})

    assert result == {
        "agent": "insights",
        "status": "error",
        "message": "Analysis report was not provided.",
    }

    assert provider.last_prompt is None
