import json
from typing import Any

from app.agents.base import BaseAgent
from app.services.llm_service import LLMService


class InsightsAgent(BaseAgent):
    """Generates AI-powered recommendations from completed analyses."""

    def __init__(self, llm_service: LLMService) -> None:
        super().__init__(
            name="insights",
            responsibility="Generate recommendations from analysis results.",
        )
        self._llm_service = llm_service

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        report = context.get("report")

        if not report:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Analysis report was not provided.",
            }

        prompt = (
            "Review the following static analysis report and provide "
            "concise, actionable recommendations for improving the project.\n\n"
            f"{json.dumps(report, indent=2)}"
        )

        response = await self._llm_service.generate(
            prompt,
            system_prompt=(
                "You are a senior Python software engineer. "
                "Base your recommendations only on the supplied analysis report."
            ),
        )

        return {
            "agent": self.name,
            "status": "completed",
            "model": response.model,
            "recommendations": response.content,
        }
