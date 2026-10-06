from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.openai_provider import OpenAIProvider


class FakeResponses:
    def __init__(self) -> None:
        self.last_request: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.last_request = kwargs

        return SimpleNamespace(
            output_text="OpenAI generated analysis."
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_openai_provider_generates_response() -> None:
    client = FakeOpenAIClient()

    provider = OpenAIProvider(
        api_key="test-key",
        model="test-model",
        client=client,
    )

    result = await provider.generate(
        "Review this Python code.",
        system_prompt="You are a senior Python reviewer.",
    )

    assert result.content == "OpenAI generated analysis."
    assert result.model == "test-model"

    assert client.responses.last_request == {
        "model": "test-model",
        "input": [
            {
                "role": "system",
                "content": "You are a senior Python reviewer.",
            },
            {
                "role": "user",
                "content": "Review this Python code.",
            },
        ],
    }