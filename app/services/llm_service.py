from app.llm.base import LLMProvider, LLMResponse


class LLMService:
    """Application service responsible for LLM interactions."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        return await self._provider.generate(
            prompt,
            system_prompt=system_prompt,
        )