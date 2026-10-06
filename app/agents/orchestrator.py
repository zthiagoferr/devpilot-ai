from typing import Any

from app.agents.base import BaseAgent


class OrchestratorAgent(BaseAgent):
    """Coordinates specialized agents without performing their analysis."""

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            responsibility="Coordinate and route analysis tasks.",
        )

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent": self.name,
            "responsibility": self.responsibility,
            "status": "ready",
            "context_received": context,
        }
