from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.fake import FakeLLMProvider
from app.llm.openai_provider import OpenAIProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    """Create the configured LLM provider."""

    if settings.llm_provider == "fake":
        return FakeLLMProvider(
            model=settings.llm_model,
        )

    if settings.llm_provider == "openai":
        if not settings.llm_api_key:
            raise ValueError(
                "LLM_API_KEY is required when LLM_PROVIDER=openai."
            )

        return OpenAIProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )

    raise ValueError(
        f"Unsupported LLM provider: {settings.llm_provider}"
    )