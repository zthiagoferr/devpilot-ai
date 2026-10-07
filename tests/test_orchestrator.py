from typing import Any

import importlib

import pytest

from app.agents.insights_agent import InsightsAgent
from app.llm.fake import FakeLLMProvider
from app.services.llm_service import LLMService
from app.agents.orchestrator import OrchestratorAgent


class StubDevelopmentAgent:
    """Deterministic DevelopmentAgent replacement for orchestrator tests."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(context.copy())
        return self.result.copy()


@pytest.mark.asyncio
async def test_orchestrator_delegates_code_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "code",
            "project_name": "devpilot-ai",
            "source_code": (
                "class UserService:\n"
                "    def get_user(self):\n"
                "        return {'id': 1}\n"
            ),
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == "code_agent"

    code_result = result["result"]

    assert code_result["agent"] == "code_agent"
    assert code_result["project_name"] == "devpilot-ai"
    assert code_result["score"] == 100
    assert code_result["issues"] == []


@pytest.mark.asyncio
async def test_orchestrator_rejects_unknown_task() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "security",
            "project_name": "devpilot-ai",
            "source_code": "print('hello')",
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "error"
    assert result["message"] == "No agent available for task: security"


@pytest.mark.asyncio
async def test_orchestrator_rejects_missing_task() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "project_name": "devpilot-ai",
            "source_code": "print('hello')",
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "error"
    assert result["message"] == "Task was not provided."


@pytest.mark.asyncio
async def test_orchestrator_delegates_test_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "tests",
            "project_name": "devpilot-ai",
            "source_code": "def test_health():\n    assert True\n",
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == "test_agent"
    assert result["result"]["agent"] == "test_agent"
    assert result["result"]["score"] == 100


@pytest.mark.asyncio
async def test_orchestrator_delegates_docs_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "docs",
            "project_name": "devpilot-ai",
            "source_code": (
                "def health_check():\n"
                '    """Return application health status."""\n'
                "    return {'status': 'healthy'}\n"
            ),
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == "docs_agent"
    assert result["result"]["agent"] == "docs_agent"
    assert result["result"]["score"] == 100


@pytest.mark.asyncio
async def test_orchestrator_runs_full_analysis() -> None:
    orchestrator = OrchestratorAgent()

    result = await orchestrator.execute(
        {
            "task": "full_analysis",
            "project_name": "devpilot-ai",
            "source_code": (
                "def test_health():\n"
                '    """Test application health."""\n'
                "    assert True\n"
            ),
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == [
        "code_agent",
        "test_agent",
        "docs_agent",
        "report_agent",
    ]

    report = result["result"]["report"]

    assert report["agent"] == "report_agent"
    assert report["project_name"] == "devpilot-ai"
    assert report["overall_score"] == 100
    assert report["total_issues"] == 0
    assert "code" in report["analyses"]
    assert "tests" in report["analyses"]
    assert "docs" in report["analyses"]


@pytest.mark.asyncio
async def test_orchestrator_runs_full_analysis_with_insights() -> None:
    provider = FakeLLMProvider(
        response="Improve test coverage and documentation.",
        model="fake-model",
    )
    service = LLMService(provider)
    insights_agent = InsightsAgent(service)

    orchestrator = OrchestratorAgent(insights_agent=insights_agent)

    result = await orchestrator.execute(
        {
            "task": "full_analysis",
            "project_name": "devpilot-ai",
            "source_code": (
                "def test_health():\n"
                '    """Test application health."""\n'
                "    assert True\n"
            ),
        }
    )

    assert result["status"] == "completed"
    assert result["delegated_to"] == [
        "code_agent",
        "test_agent",
        "docs_agent",
        "report_agent",
        "insights",
    ]
    assert "report" in result["result"]
    assert "insights" in result["result"]

    insights = result["result"]["insights"]

    assert insights["agent"] == "insights"
    assert insights["status"] == "completed"
    assert insights["model"] == "fake-model"
    assert insights["recommendations"] == "Improve test coverage and documentation."
    assert provider.last_prompt is not None
    assert "devpilot-ai" in provider.last_prompt


@pytest.mark.asyncio
async def test_orchestrator_successfully_delegates_multi_file_develop() -> None:
    development_result = {
        "agent": "development_agent",
        "status": "completed",
        "completed_tasks": [
            {"file_path": "src/one.py", "task": "Create one."},
            {"file_path": "src/two.py", "task": "Create two."},
        ],
    }
    development_agent = StubDevelopmentAgent(development_result)
    orchestrator = OrchestratorAgent(development_agent=development_agent)
    context = {
        "task": "multi_file_develop",
        "project_name": "devpilot-ai",
        "development_goal": "Create two modules.",
        "file_tasks": [
            {"file_path": "src/one.py", "task": "Create one."},
            {"file_path": "src/two.py", "task": "Create two."},
        ],
    }

    result = await orchestrator.execute(context)

    assert result["agent"] == "orchestrator"
    assert result["status"] == "completed"
    assert result["delegated_to"] == "development_agent"
    assert result["result"] == development_result
    assert development_agent.calls == [
        {
            "development_goal": context["development_goal"],
            "file_tasks": context["file_tasks"],
        }
    ]


@pytest.mark.asyncio
async def test_orchestrator_propagates_multi_file_develop_failure() -> None:
    development_result = {
        "agent": "development_agent",
        "status": "failed",
        "message": "coding failed",
        "completed_tasks": [],
    }
    development_agent = StubDevelopmentAgent(development_result)
    orchestrator = OrchestratorAgent(development_agent=development_agent)

    result = await orchestrator.execute(
        {
            "task": "multi_file_develop",
            "development_goal": "Update the application.",
            "file_tasks": [{"file_path": "app.py", "task": "Update app."}],
        }
    )

    assert result["agent"] == "orchestrator"
    assert result["status"] == "failed"
    assert result["delegated_to"] == "development_agent"
    assert result["result"] == development_result
    assert len(development_agent.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "context",
    [
        {
            "task": "multi_file_develop",
            "file_tasks": [{"file_path": "app.py", "task": "Create app."}],
        },
        {
            "task": "multi_file_develop",
            "development_goal": "Create the application.",
        },
    ],
)
async def test_orchestrator_rejects_multi_file_develop_missing_required_context(
    context: dict[str, Any],
) -> None:
    development_agent = StubDevelopmentAgent(
        {"agent": "development_agent", "status": "completed"}
    )
    orchestrator = OrchestratorAgent(development_agent=development_agent)

    result = await orchestrator.execute(context)

    assert result["agent"] == "orchestrator"
    assert result["status"] == "error"
    assert development_agent.calls == []


class _RegistryEchoTool:
    """Canonical V5 tool used only for registry integration tests."""

    def __new__(cls):
        from app.tools.base import BaseTool

        class RegistryEchoTool(BaseTool):
            def __init__(self) -> None:
                super().__init__(
                    name="injected_echo",
                    description="A deterministic injected tool.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "value": {"type": "string"},
                        },
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                )

            async def execute(self, **kwargs: Any) -> dict[str, Any]:
                return {"value": kwargs["value"]}

        return RegistryEchoTool()


def test_v5_runtime_dependencies_can_be_injected_and_are_isolated() -> None:
    first_agent = StubDevelopmentAgent(
        {"agent": "first", "status": "completed"}
    )
    second_agent = StubDevelopmentAgent(
        {"agent": "second", "status": "completed"}
    )

    first = OrchestratorAgent(development_agent=first_agent)
    second = OrchestratorAgent(development_agent=second_agent)

    first_dependency = getattr(
        first,
        "development_agent",
        first._development_agent,
    )
    second_dependency = getattr(
        second,
        "development_agent",
        second._development_agent,
    )

    assert first_dependency is first_agent
    assert second_dependency is second_agent
    assert first_dependency is not second_dependency


def test_v5_custom_registries_support_registration_discovery_and_isolation() -> None:
    from app.tools import ToolRegistry

    first = ToolRegistry()
    second = ToolRegistry()
    tool = _RegistryEchoTool()

    first.register(tool)

    assert first.lookup("injected_echo") is tool
    assert second.lookup("injected_echo") is None

    first_names = {
        item["name"]
        for item in first.discovery_metadata()
    }
    second_names = {
        item["name"]
        for item in second.discovery_metadata()
    }

    assert "injected_echo" in first_names
    assert "injected_echo" not in second_names


def test_v5_default_project_tools_are_discoverable_without_shell_access(
    tmp_path,
) -> None:
    from app.tools import create_default_project_registry

    registry = create_default_project_registry(tmp_path)
    names = {
        item["name"]
        for item in registry.discovery_metadata()
    }

    assert {"list_files", "read_file", "write_file"}.issubset(names)
    assert not names.intersection(
        {"shell", "run_shell", "execute_command"}
    )


def test_v5_registries_do_not_require_a_module_global_mutable_registry() -> None:
    from app.tools import ToolRegistry

    first = ToolRegistry()
    second = ToolRegistry()

    first.register(_RegistryEchoTool())

    assert first.lookup("injected_echo") is not None
    assert second.lookup("injected_echo") is None

