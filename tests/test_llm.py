import pytest

from app.llm.base import LLMProvider
from app.llm.fake import FakeLLMProvider


def test_llm_provider_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        LLMProvider()


@pytest.mark.asyncio
async def test_fake_llm_provider_returns_configured_response() -> None:
    provider = FakeLLMProvider(
        response="Code quality looks good.",
        model="fake-test-model",
    )

    result = await provider.generate(
        "Analyze this Python code.",
        system_prompt="You are a code reviewer.",
    )

    assert result.content == "Code quality looks good."
    assert result.model == "fake-test-model"
    assert provider.last_prompt == "Analyze this Python code."
    assert provider.last_system_prompt == "You are a code reviewer."