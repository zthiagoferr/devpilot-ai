from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Base contract for tools available to DevPilot agents."""

    def __init__(
        self,
        name: str,
        description: str,
    ) -> None:
        self.name = name
        self.description = description

    @abstractmethod
    async def execute(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the tool and return a structured result."""
        raise NotImplementedError
