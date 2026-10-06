from typing import Any

from app.agents.base import BaseAgent
from app.agents.code_agent import CodeAgent
from app.agents.coding_agent import CodingAgent
from app.agents.docs_agent import DocsAgent
from app.agents.insights_agent import InsightsAgent
from app.agents.report_agent import ReportAgent
from app.agents.test_agent import TestAgent


class OrchestratorAgent(BaseAgent):
    """Coordinates specialized agents without performing their work."""

    def __init__(
        self,
        insights_agent: InsightsAgent | None = None,
        coding_agent: CodingAgent | None = None,
    ) -> None:
        super().__init__(
            name="orchestrator",
            responsibility="Coordinate and route tasks to specialized agents.",
        )

        self._agents: dict[str, BaseAgent] = {
            "code": CodeAgent(),
            "tests": TestAgent(),
            "docs": DocsAgent(),
        }

        self._report_agent = ReportAgent()
        self._insights_agent = insights_agent
        self._coding_agent = coding_agent

    async def execute(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        task = context.get("task")

        if not task:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Task was not provided.",
            }

        if task == "develop":
            return await self._execute_development(context)

        if task == "full_analysis":
            return await self._execute_full_analysis(context)

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

    async def _execute_development(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self._coding_agent is None:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Coding agent is not configured.",
            }

        development_task = context.get("development_task")
        file_path = context.get("file_path")

        if not development_task:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Development task was not provided.",
            }

        if not file_path:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Target file was not provided.",
            }

        result = await self._coding_agent.execute(
            {
                "task": development_task,
                "file_path": file_path,
            }
        )

        return {
            "agent": self.name,
            "status": result["status"],
            "delegated_to": self._coding_agent.name,
            "result": result,
        }

    async def _execute_full_analysis(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        analyses: dict[str, Any] = {}

        for agent_task in ("code", "tests", "docs"):
            agent = self._agents[agent_task]
            analyses[agent_task] = await agent.execute(context)

        report = await self._report_agent.execute(
            {
                "project_name": context["project_name"],
                "analyses": analyses,
            }
        )

        delegated_to = [
            self._agents["code"].name,
            self._agents["tests"].name,
            self._agents["docs"].name,
            self._report_agent.name,
        ]

        result: dict[str, Any] = {
            "report": report,
        }

        if self._insights_agent is not None:
            insights = await self._insights_agent.execute(
                {
                    "report": report,
                }
            )

            delegated_to.append(self._insights_agent.name)
            result["insights"] = insights

        return {
            "agent": self.name,
            "status": "completed",
            "delegated_to": delegated_to,
            "result": result,
        }