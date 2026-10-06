import json

import pytest

from app.agents.planning_agent import PlanningAgent
from app.llm.fake import FakeLLMProvider
from app.services.llm_service import LLMService


def _agent(tmp_path, response):
    provider = FakeLLMProvider(
        response=json.dumps(response) if isinstance(response, dict) else response,
        model="fake-model",
    )
    agent = PlanningAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
    )
    return agent, provider


@pytest.mark.asyncio
async def test_planning_agent_creates_file_tasks_for_high_level_goal(tmp_path) -> None:
    response = {
        "development_goal": "Add a health-check endpoint.",
        "file_tasks": [
            {
                "file_path": "app/routes/health.py",
                "task": "Implement the health-check endpoint.",
            },
            {
                "file_path": "tests/test_health.py",
                "task": "Add tests for the health-check endpoint.",
            },
        ],
    }
    agent, provider = _agent(tmp_path, response)

    result = await agent.execute(
        {"development_goal": "Add a health-check endpoint."}
    )

    assert result["agent"] == "planning_agent"
    assert result["status"] == "completed"
    assert result["development_goal"] == "Add a health-check endpoint."
    assert result["file_tasks"] == response["file_tasks"]
    assert set(("agent", "status", "development_goal", "file_tasks")).issubset(result)
    assert provider.last_prompt is not None
    assert "Add a health-check endpoint." in provider.last_prompt


@pytest.mark.asyncio
async def test_planning_agent_rejects_invalid_json(tmp_path) -> None:
    agent, provider = _agent(tmp_path, "not valid json")

    result = await agent.execute(
        {"development_goal": "Create a command-line interface."}
    )

    assert result["agent"] == "planning_agent"
    assert result["status"] == "error"
    assert provider.last_prompt is not None
    assert "Create a command-line interface." in provider.last_prompt
    assert "file_tasks" not in result or result["file_tasks"] == []


@pytest.mark.asyncio
async def test_planning_agent_rejects_empty_plans(tmp_path) -> None:
    agent, _ = _agent(
        tmp_path,
        {"development_goal": "Improve the application.", "file_tasks": []},
    )

    result = await agent.execute(
        {"development_goal": "Improve the application."}
    )

    assert result["agent"] == "planning_agent"
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_planning_agent_rejects_more_than_twelve_file_tasks(tmp_path) -> None:
    tasks = [
        {"file_path": f"src/module_{index}.py", "task": "Update this module."}
        for index in range(13)
    ]
    agent, _ = _agent(
        tmp_path,
        {"development_goal": "Refactor the project.", "file_tasks": tasks},
    )

    result = await agent.execute({"development_goal": "Refactor the project."})

    assert result["agent"] == "planning_agent"
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_planning_agent_rejects_duplicate_paths(tmp_path) -> None:
    tasks = [
        {"file_path": "app/service.py", "task": "Implement the service."},
        {"file_path": "app/service.py", "task": "Add service tests."},
    ]
    agent, _ = _agent(
        tmp_path,
        {"development_goal": "Build a service.", "file_tasks": tasks},
    )

    result = await agent.execute({"development_goal": "Build a service."})

    assert result["agent"] == "planning_agent"
    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_path",
    [
        "../outside.py",
        "nested/../../outside.py",
        ".env",
        ".git/config",
        ".venv/bin/python",
    ],
)
async def test_planning_agent_rejects_unsafe_file_paths(tmp_path, file_path) -> None:
    agent, _ = _agent(
        tmp_path,
        {
            "development_goal": "Update the project.",
            "file_tasks": [{"file_path": file_path, "task": "Make a change."}],
        },
    )

    result = await agent.execute({"development_goal": "Update the project."})

    assert result["agent"] == "planning_agent"
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_planning_agent_rejects_absolute_file_paths(tmp_path) -> None:
    absolute_path = str(tmp_path / "outside.py")
    agent, _ = _agent(
        tmp_path,
        {
            "development_goal": "Update the project.",
            "file_tasks": [
                {"file_path": absolute_path, "task": "Write outside the project."}
            ],
        },
    )

    result = await agent.execute({"development_goal": "Update the project."})

    assert result["agent"] == "planning_agent"
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_planning_agent_prompt_does_not_expose_unsafe_repository_files(
    tmp_path,
) -> None:
    (tmp_path / "app.py").write_text(
        "from helper import increment\n\ndef run(value):\n    return increment(value)\n",
        encoding="utf-8",
    )
    (tmp_path / "helper.py").write_text(
        "def increment(value):\n    return value + 1\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "The application uses helper.increment.\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "API_KEY=DO_NOT_SEND_THIS_SECRET\n", encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text(
        "SECRET_GIT_CONFIGURATION\n", encoding="utf-8"
    )
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "config.py").write_text(
        "SECRET_VENV_CONFIGURATION\n", encoding="utf-8"
    )

    agent, provider = _agent(
        tmp_path,
        {
            "development_goal": "Improve the application using the helper module.",
            "file_tasks": [{"file_path": "app.py", "task": "Improve run."}],
        },
    )

    result = await agent.execute(
        {"development_goal": "Improve the application using the helper module."}
    )

    assert result["status"] == "completed"
    assert provider.last_prompt is not None
    prompt = provider.last_prompt
    assert "Improve the application using the helper module." in prompt
    assert "DO_NOT_SEND_THIS_SECRET" not in prompt
    assert "SECRET_GIT_CONFIGURATION" not in prompt
    assert "SECRET_VENV_CONFIGURATION" not in prompt
    assert "File: .env" not in prompt
    assert "File: .git/config" not in prompt
    assert "File: .venv/config.py" not in prompt
