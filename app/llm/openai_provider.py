from typing import Any

from openai import AsyncOpenAI

from app.llm.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    """LLM provider backed by the OpenAI Responses API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        self._client = client or AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        input_messages: list[dict[str, str]] = []

        if system_prompt:
            input_messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        input_messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        response = await self._client.responses.create(
            model=self._model,
            input=input_messages,
        )

        return LLMResponse(
            content=response.output_text,
            model=self._model,
        )