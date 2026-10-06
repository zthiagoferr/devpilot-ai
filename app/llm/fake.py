from app.llm.base import LLMProvider, LLMResponse


class FakeLLMProvider(LLMProvider):
    """Deterministic LLM provider used for tests."""

    def __init__(
        self,
        response: str = "Fake LLM response.",
        model: str = "fake-model",
    ) -> None:
        self.response = response
        self.model = model
        self.last_prompt: str | None = None
        self.last_system_prompt: str | None = None

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt

        return LLMResponse(
            content=self.response,
            model=self.model,
        )