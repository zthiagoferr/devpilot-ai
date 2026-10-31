from typing import Any
from uuid import uuid4

from openai import AsyncOpenAI

from app.llm.base import IncompleteLLMResponseError, LLMProvider, LLMResponse


class OpenCodeProvider(LLMProvider):
    """LLM provider backed by the OpenCode Go API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        session_id = str(uuid4())

        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url="https://opencode.ai/zen/go/v1",
            default_headers={
                "User-Agent": "devpilot-ai/0.1.0",
                "x-opencode-session": session_id,
            },
        )
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

        status = getattr(response, "status", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        if status == "incomplete" or incomplete_details is not None:
            raise IncompleteLLMResponseError(
                "The AI provider returned an incomplete response."
            )

        return LLMResponse(
            content=response.output_text,
            model=self._model,
        )