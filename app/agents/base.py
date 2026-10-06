from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Base contract for every specialized DevPilot AI agent."""

    def __init__(self, name: str, responsibility: str) -> None:
        self.name = name
        self.responsibility = responsibility

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute only the responsibility assigned to this agent."""
        raise NotImplementedError