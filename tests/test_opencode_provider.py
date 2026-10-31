from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.base import IncompleteLLMResponseError
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


class IncompleteResponses:
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            output_text="",
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
        )


class IncompleteOpenCodeClient:
    def __init__(self) -> None:
        self.responses = IncompleteResponses()


@pytest.mark.asyncio
async def test_opencode_provider_rejects_an_incomplete_response() -> None:
    provider = OpenCodeProvider(
        api_key="test-key",
        model="deepseek-v4.1-flash",
        client=IncompleteOpenCodeClient(),
    )

    with pytest.raises(IncompleteLLMResponseError):
        await provider.generate("Return JSON.")


class IncompleteDetailsOnlyResponses:
    async def create(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            output_text="partial",
            incomplete_details={"reason": "max_output_tokens"},
        )


class IncompleteDetailsOnlyClient:
    def __init__(self) -> None:
        self.responses = IncompleteDetailsOnlyResponses()


@pytest.mark.asyncio
async def test_opencode_provider_rejects_non_null_incomplete_details() -> None:
    provider = OpenCodeProvider(
        api_key="test-key",
        model="deepseek-v4.1-flash",
        client=IncompleteDetailsOnlyClient(),
    )

    with pytest.raises(IncompleteLLMResponseError):
        await provider.generate("Return JSON.")
