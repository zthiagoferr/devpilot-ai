from abc import ABC, abstractmethod
from dataclasses import dataclass


class IncompleteLLMResponseError(RuntimeError):
    """Raised when the provider marks its response as incomplete.

    An incomplete response has no usable ``output_text``; returning an empty
    string would look like a malformed correction payload. The provider layer
    signals the real condition and upper layers translate it.
    """


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