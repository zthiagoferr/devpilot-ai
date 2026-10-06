from typing import Any

from app.agents.base import BaseAgent
from app.agents.code_agent import CodeAgent
from app.agents.coding_agent import CodingAgent
from app.agents.development_agent import DevelopmentAgent
from app.agents.docs_agent import DocsAgent
from app.agents.insights_agent import InsightsAgent
from app.agents.planning_agent import PlanningAgent
from app.agents.report_agent import ReportAgent
from app.agents.test_agent import TestAgent


class OrchestratorAgent(BaseAgent):
    """Coordinates specialized agents without performing their work."""

    def __init__(
        self,
        insights_agent: InsightsAgent | None = None,
        coding_agent: CodingAgent | None = None,
        development_agent: DevelopmentAgent | None = None,
        planning_agent: PlanningAgent | None = None,
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
        self._planning_agent = planning_agent
        self._development_agent = development_agent

    @staticmethod
    def _agent_name(agent: Any, fallback: str) -> str:
        return str(getattr(agent, "name", fallback))

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

        if task == "multi_file_develop":
            return await self._execute_multi_file_development(context)

        if task == "autonomous_develop":
            return await self._execute_autonomous_development(context)

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

    async def _execute_multi_file_development(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        development_goal = context.get("development_goal")
        file_tasks = context.get("file_tasks")

        if not development_goal:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Development goal was not provided.",
            }

        if not file_tasks:
            return {
                "agent": self.name,
                "status": "error",
                "message": "File tasks were not provided.",
            }

        if self._development_agent is None:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Development agent is not configured.",
            }

        result = await self._development_agent.execute(
            {
                "development_goal": development_goal,
                "file_tasks": file_tasks,
            }
        )

        return {
            "agent": self.name,
            "status": result["status"],
            "delegated_to": self._agent_name(
                self._development_agent, "development_agent"
            ),
            "result": result,
        }

    async def _execute_autonomous_development(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        development_goal = context.get("development_goal")
        delegated_agents: list[str] = []

        if not development_goal:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Development goal was not provided.",
                "planning_result": None,
                "development_result": None,
                "delegated_agents": delegated_agents,
                "delegated_to": delegated_agents,
            }

        if self._planning_agent is None:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Planning agent is not configured.",
                "planning_result": None,
                "development_result": None,
                "delegated_agents": delegated_agents,
                "delegated_to": "planning_agent",
            }

        planning_agent_name = self._agent_name(
            self._planning_agent, "planning_agent"
        )
        delegated_agents.append(planning_agent_name)

        planning_result = await self._planning_agent.execute(
            {
                "development_goal": development_goal,
            }
        )
        planning_status = planning_result.get("status", "failed")

        if planning_status != "completed":
            return {
                "agent": self.name,
                "status": planning_status,
                "planning_result": planning_result,
                "development_result": None,
                "delegated_agents": delegated_agents,
                "delegated_to": "planning_agent",
            }

        file_tasks = planning_result.get("file_tasks")
        if not file_tasks:
            return {
                "agent": self.name,
                "status": "failed",
                "message": "Planning did not provide validated file tasks.",
                "planning_result": planning_result,
                "development_result": None,
                "delegated_agents": delegated_agents,
                "delegated_to": "planning_agent",
            }

        if self._development_agent is None:
            return {
                "agent": self.name,
                "status": "error",
                "message": "Development agent is not configured.",
                "planning_result": planning_result,
                "development_result": None,
                "delegated_agents": delegated_agents,
                "delegated_to": "planning_agent",
            }

        development_agent_name = self._agent_name(
            self._development_agent, "development_agent"
        )
        development_result = await self._development_agent.execute(
            {
                "development_goal": development_goal,
                "file_tasks": file_tasks,
            }
        )
        delegated_agents.append(development_agent_name)

        return {
            "agent": self.name,
            "status": development_result.get("status", "failed"),
            "planning_result": planning_result,
            "development_result": development_result,
            "delegated_agents": delegated_agents,
            "delegated_to": ["planning_agent", "development_agent"],
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
