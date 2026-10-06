from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.opencode_provider import OpenCodeProvider


class FakeResponses:
    def __init__(self) -> None:
        self.last_request: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.last_request = kwargs

        return SimpleNamespace(
            output_text="OpenCode generated analysis."
        )


class FakeOpenCodeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_opencode_provider_generates_response() -> None:
    client = FakeOpenCodeClient()

    provider = OpenCodeProvider(
        api_key="test-key",
        model="gpt-5.6-luna",
        client=client,
    )

    result = await provider.generate(
        "Review this Python code.",
        system_prompt="You are a senior Python reviewer.",
    )

    assert result.content == "OpenCode generated analysis."
    assert result.model == "gpt-5.6-luna"

    assert client.responses.last_request == {
        "model": "gpt-5.6-luna",
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
