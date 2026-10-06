import pytest

from app.llm.fake import FakeLLMProvider
from app.services.llm_service import LLMService


@pytest.mark.asyncio
async def test_llm_service_uses_configured_provider() -> None:
    provider = FakeLLMProvider(
        response="Generated analysis.",
        model="fake-test-model",
    )

    service = LLMService(provider)

    result = await service.generate(
        "Review this code.",
        system_prompt="You are a senior Python reviewer.",
    )

    assert result.content == "Generated analysis."
    assert result.model == "fake-test-model"

    assert provider.last_prompt == "Review this code."
    assert (
        provider.last_system_prompt
        == "You are a senior Python reviewer."
    )