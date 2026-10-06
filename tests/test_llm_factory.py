import pytest
from app.llm.opencode_provider import OpenCodeProvider
from app.core.config import Settings
from app.llm.fake import FakeLLMProvider
from app.llm.factory import create_llm_provider
from app.llm.openai_provider import OpenAIProvider


def test_factory_creates_fake_provider() -> None:
    settings = Settings(
        llm_provider="fake",
        llm_model="fake-test-model",
        _env_file=None,
    )

    provider = create_llm_provider(settings)

    assert isinstance(provider, FakeLLMProvider)
    assert provider.model == "fake-test-model"


def test_factory_creates_openai_provider() -> None:
    settings = Settings(
        llm_provider="openai",
        llm_model="test-model",
        llm_api_key="test-key",
        _env_file=None,
    )

    provider = create_llm_provider(settings)

    assert isinstance(provider, OpenAIProvider)


def test_factory_rejects_openai_without_api_key() -> None:
    settings = Settings(
        llm_provider="openai",
        llm_model="test-model",
        llm_api_key=None,
        _env_file=None,
    )

    with pytest.raises(
        ValueError,
        match="LLM_API_KEY is required",
    ):
        create_llm_provider(settings)


def test_factory_rejects_unknown_provider() -> None:
    settings = Settings(
        llm_provider="unknown",
        _env_file=None,
    )

    with pytest.raises(
        ValueError,
        match="Unsupported LLM provider",
    ):
        create_llm_provider(settings)
def test_factory_creates_opencode_provider() -> None:
    settings = Settings(
        llm_provider="opencode",
        llm_model="gpt-5.6-luna",
        llm_api_key="test-key",
        _env_file=None,
    )

    provider = create_llm_provider(settings)

    assert isinstance(provider, OpenCodeProvider)


def test_factory_rejects_opencode_without_api_key() -> None:
    settings = Settings(
        llm_provider="opencode",
        llm_model="gpt-5.6-luna",
        llm_api_key=None,
        _env_file=None,
    )

    with pytest.raises(
        ValueError,
        match="LLM_API_KEY is required",
    ):
        create_llm_provider(settings)
