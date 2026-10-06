from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResponse:
    """Standard response returned by an LLM provider."""

    content: str
    model: str


class LLMProvider(ABC):
    """Base contract for every LLM provider."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Generate a response from a language model."""
        raise NotImplementedError