import importlib
import inspect
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


class _LocalToolRegistry:
    """Small per-runtime registry used when the V5 registry is unavailable.

    The registry intentionally has no module-level state.  It provides the
    minimal registry protocol needed by callers that inject tools in tests or
    by an orchestration runtime that does not install the full V5 registry.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, tool: Any) -> Any:
        name = getattr(tool, "name", None)
        if not name:
            raise ValueError("A tool must provide a name.")
        self._tools[str(name)] = tool
        return tool

    def get(self, name: str, default: Any = None) -> Any:
        return self._tools.get(name, default)

    def get_tool(self, name: str, default: Any = None) -> Any:
        return self.get(name, default)

    def all(self) -> dict[str, Any]:
        return dict(self._tools)

    def list_tools(self) -> list[Any]:
        return list(self._tools.values())


def _dependency_value(dependencies: Any, name: str) -> Any:
    if dependencies is None:
        return None
    if isinstance(dependencies, dict):
        return dependencies.get(name)
    return getattr(dependencies, name, None)


def _create_project_tool_registry(dependencies: Any = None) -> Any:
    """Create a new approved project registry for one orchestration flow."""
    supplied = _dependency_value(dependencies, "tool_registry")
    if supplied is not None:
        return supplied

    factory = _dependency_value(dependencies, "create_tool_registry")
    project_root = _dependency_value(dependencies, "project_root")
    if callable(factory):
        try:
            return factory(project_root=project_root)
        except TypeError:
            return factory()

    # V5 has used both registry module names while being introduced.  Keep
    # this lookup local so importing the orchestrator does not create or share
    # a process-wide registry.
    for module_name in ("app.tools.registry", "app.tools.tool_registry"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue

        for factory_name in (
            "create_project_tool_registry",
            "create_approved_project_tool_registry",
            "create_approved_tool_registry",
        ):
            candidate = getattr(module, factory_name, None)
            if not callable(candidate):
                continue
            try:
                if project_root is not None:
                    return candidate(project_root=project_root)
                return candidate()
            except TypeError:
                return candidate()

        registry_type = getattr(module, "ToolRegistry", None)
        if registry_type is not None:
            try:
                registry = registry_type()
            except TypeError:
                if project_root is None:
                    continue
                registry = registry_type(project_root=project_root)
            approved = getattr(module, "approved_project_tools", None)
            if callable(approved):
                for tool in approved(project_root=project_root):
                    registry.register(tool)
            return registry

    return _LocalToolRegistry()


def _construct_agent(agent_type: Any, dependencies: Any, tool_registry: Any) -> Any:
    """Construct an agent while passing only dependencies it declares."""
    try:
        signature = inspect.signature(agent_type)
    except (TypeError, ValueError):
        return agent_type()

    parameters = signature.parameters
    kwargs: dict[str, Any] = {}
    if "tool_registry" in parameters:
        kwargs["tool_registry"] = tool_registry
    if "runtime_dependencies" in parameters:
        kwargs["runtime_dependencies"] = dependencies
    elif "runtime" in parameters:
        kwargs["runtime"] = dependencies
    elif "dependencies" in parameters:
        kwargs["dependencies"] = dependencies
    return agent_type(**kwargs)


class OrchestratorAgent(BaseAgent):
    """Coordinates specialized agents without performing their work."""

    def __init__(
        self,
        insights_agent: InsightsAgent | None = None,
        coding_agent: CodingAgent | None = None,
        development_agent: DevelopmentAgent | None = None,
        planning_agent: PlanningAgent | None = None,
        *,
        tool_registry: Any | None = None,
        runtime_dependencies: Any | None = None,
        runtime: Any | None = None,
        dependencies: Any | None = None,
    ) -> None:
        super().__init__(
            name="orchestrator",
            responsibility="Coordinate and route tasks to specialized agents.",
        )

        injected_runtime = (
            runtime_dependencies
            if runtime_dependencies is not None
            else runtime if runtime is not None else dependencies
        )
        self.runtime_dependencies = injected_runtime
        self._runtime_dependencies = injected_runtime
        self.tool_registry = (
            tool_registry
            if tool_registry is not None
            else _create_project_tool_registry(injected_runtime)
        )
        self._tool_registry = self.tool_registry

        self._agents: dict[str, BaseAgent] = {
            "code": _construct_agent(CodeAgent, injected_runtime, self.tool_registry),
            "tests": _construct_agent(TestAgent, injected_runtime, self.tool_registry),
            "docs": _construct_agent(DocsAgent, injected_runtime, self.tool_registry),
        }

        self._report_agent = _construct_agent(
            ReportAgent, injected_runtime, self.tool_registry
        )
        self._insights_agent = insights_agent
        self._coding_agent = coding_agent
        self._planning_agent = planning_agent
        self._development_agent = development_agent

    @staticmethod
    def _agent_name(agent: Any, fallback: str) -> str:
        return str(getattr(agent, "name", fallback))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context.get("task")

        if not task:
            return {"agent": self.name, "status": "error", "message": "Task was not provided."}

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
            return {"agent": self.name, "status": "error", "message": f"No agent available for task: {task}"}
        result = await selected_agent.execute(context)
        return {"agent": self.name, "status": "completed", "delegated_to": selected_agent.name, "result": result}

    async def _execute_development(self, context: dict[str, Any]) -> dict[str, Any]:
        if self._coding_agent is None:
            return {"agent": self.name, "status": "error", "message": "Coding agent is not configured."}
        development_task = context.get("development_task")
        file_path = context.get("file_path")
        if not development_task:
            return {"agent": self.name, "status": "error", "message": "Development task was not provided."}
        if not file_path:
            return {"agent": self.name, "status": "error", "message": "Target file was not provided."}
        result = await self._coding_agent.execute({"task": development_task, "file_path": file_path})
        return {"agent": self.name, "status": result["status"], "delegated_to": self._coding_agent.name, "result": result}

    async def _execute_multi_file_development(self, context: dict[str, Any]) -> dict[str, Any]:
        development_goal = context.get("development_goal")
        file_tasks = context.get("file_tasks")
        if not development_goal:
            return {"agent": self.name, "status": "error", "message": "Development goal was not provided."}
        if not file_tasks:
            return {"agent": self.name, "status": "error", "message": "File tasks were not provided."}
        if self._development_agent is None:
            return {"agent": self.name, "status": "error", "message": "Development agent is not configured."}
        result = await self._development_agent.execute({"development_goal": development_goal, "file_tasks": file_tasks})
        return {"agent": self.name, "status": result["status"], "delegated_to": self._agent_name(self._development_agent, "development_agent"), "result": result}

    async def _execute_autonomous_development(self, context: dict[str, Any]) -> dict[str, Any]:
        goal = context.get("development_goal")
        delegated: list[str] = []
        base = {"agent": self.name, "planning_result": None, "development_result": None, "delegated_agents": delegated}
        if not goal:
            return {**base, "status": "error", "message": "Development goal was not provided.", "delegated_to": delegated}
        if self._planning_agent is None:
            return {**base, "status": "error", "message": "Planning agent is not configured.", "delegated_to": "planning_agent"}
        delegated.append(self._agent_name(self._planning_agent, "planning_agent"))
        planning = await self._planning_agent.execute({"development_goal": goal})
        if planning.get("status", "failed") != "completed":
            return {**base, "status": planning.get("status", "failed"), "planning_result": planning, "delegated_to": "planning_agent"}
        tasks = planning.get("file_tasks")
        if not tasks:
            return {**base, "status": "failed", "message": "Planning did not provide validated file tasks.", "planning_result": planning, "delegated_to": "planning_agent"}
        if self._development_agent is None:
            return {**base, "status": "error", "message": "Development agent is not configured.", "planning_result": planning, "delegated_to": "planning_agent"}
        development = await self._development_agent.execute({"development_goal": goal, "file_tasks": tasks})
        delegated.append(self._agent_name(self._development_agent, "development_agent"))
        return {"agent": self.name, "status": development.get("status", "failed"), "planning_result": planning, "development_result": development, "delegated_agents": delegated, "delegated_to": ["planning_agent", "development_agent"]}

    async def _execute_full_analysis(self, context: dict[str, Any]) -> dict[str, Any]:
        analyses = {task: await self._agents[task].execute(context) for task in ("code", "tests", "docs")}
        report = await self._report_agent.execute({"project_name": context["project_name"], "analyses": analyses})
        delegated = [self._agents[t].name for t in ("code", "tests", "docs")] + [self._report_agent.name]
        result: dict[str, Any] = {"report": report}
        if self._insights_agent is not None:
            result["insights"] = await self._insights_agent.execute({"report": report})
            delegated.append(self._insights_agent.name)
        return {"agent": self.name, "status": "completed", "delegated_to": delegated, "result": result}
