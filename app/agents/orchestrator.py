from typing import Any
from app.agents.docs_agent import DocsAgent
from app.agents.base import BaseAgent
from app.agents.code_agent import CodeAgent
from app.agents.test_agent import TestAgent


class OrchestratorAgent(BaseAgent):
    """Coordinates specialized agents without performing their analysis."""

    def __init__(self) -> None:
        super().__init__(
            name="orchestrator",
            responsibility="Coordinate and route analysis tasks.",
        )

        self._agents: dict[str, BaseAgent] = {
         "code": CodeAgent(),
         "tests": TestAgent(),
         "docs": DocsAgent(),
}
       

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task")

        if not task:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Task was not provided.",
            }

        selected_agent = self._agents.get(task)

        if selected_agent is None:
            return {
                "agent": self.name,
                "status": "error",
                "message": f"No agent available for task: {task}",
            }

        result = await selected_agent.execute(context)

        return {
            "agent": self.name,
            "status": "completed",
            "delegated_to": selected_agent.name,
            "result": result,
        }