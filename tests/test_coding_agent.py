import json

import pytest

from app.agents.coding_agent import CodingAgent
from app.llm.base import LLMProvider, LLMResponse
from app.llm.fake import FakeLLMProvider
from app.services.llm_service import LLMService


class SequentialFakeLLMProvider(LLMProvider):
    """Returns predefined responses sequentially."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.call_count = 0
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        self.prompts.append(prompt)

        response = self.responses[self.call_count]
        self.call_count += 1

        return LLMResponse(
            content=response,
            model="fake-model",
        )


@pytest.mark.asyncio
async def test_coding_agent_writes_file_and_runs_tests(
    tmp_path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "def add(a, b):\n"
        "    return 0\n",
        encoding="utf-8",
    )

    test_file = tmp_path / "test_example.py"
    test_file.write_text(
        "from example import add\n\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    generated_code = (
        "def add(a, b):\n"
        "    return a + b\n"
    )

    provider = FakeLLMProvider(
        response=json.dumps(
            {
                "content": generated_code,
            }
        ),
        model="fake-model",
    )

    service = LLMService(provider)

    agent = CodingAgent(
        llm_service=service,
        project_root=tmp_path,
    )

    result = await agent.execute(
        {
            "task": "Fix the add function.",
            "file_path": "example.py",
        }
    )

    assert result["agent"] == "coding_agent"
    assert result["status"] == "completed"
    assert result["model"] == "fake-model"
    assert result["file"] == "example.py"
    assert result["attempts"] == 1

    assert target.read_text(
        encoding="utf-8",
    ) == generated_code

    assert result["tests"]["return_code"] == 0
    assert provider.last_prompt is not None
    assert "Fix the add function." in provider.last_prompt


@pytest.mark.asyncio
async def test_coding_agent_rejects_invalid_llm_response(
    tmp_path,
) -> None:
    provider = FakeLLMProvider(
        response="this is not json",
    )

    service = LLMService(provider)

    agent = CodingAgent(
        llm_service=service,
        project_root=tmp_path,
    )

    result = await agent.execute(
        {
            "task": "Create something.",
            "file_path": "example.py",
        }
    )

    assert result["status"] == "error"
    assert result["message"] == (
        "LLM returned an invalid coding response."
    )

    assert not (
        tmp_path / "example.py"
    ).exists()


@pytest.mark.asyncio
async def test_coding_agent_repairs_failed_tests(
    tmp_path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "def add(a, b):\n"
        "    return 0\n",
        encoding="utf-8",
    )

    test_file = tmp_path / "test_example.py"
    test_file.write_text(
        "from example import add\n\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    broken_code = (
        "def add(a, b):\n"
        "    return a - b\n"
    )

    fixed_code = (
        "def add(a, b):\n"
        "    return a + b\n"
    )

    provider = SequentialFakeLLMProvider(
        responses=[
            json.dumps(
                {
                    "content": broken_code,
                }
            ),
            json.dumps(
                {
                    "content": fixed_code,
                }
            ),
        ]
    )

    service = LLMService(provider)

    agent = CodingAgent(
        llm_service=service,
        project_root=tmp_path,
        max_attempts=2,
    )

    result = await agent.execute(
        {
            "task": "Fix the add function.",
            "file_path": "example.py",
        }
    )

    assert result["status"] == "completed"
    assert result["attempts"] == 2
    assert provider.call_count == 2

    assert target.read_text(
        encoding="utf-8",
    ) == fixed_code

    assert "Previous test execution failed." in provider.prompts[1]
    assert "FAILED" in provider.prompts[1]

    assert result["tests"]["return_code"] == 0


@pytest.mark.asyncio
async def test_coding_agent_restores_existing_file_after_all_attempts_fail(
    tmp_path,
) -> None:
    target = tmp_path / "example.py"
    original_content = (
        "def add(a, b):\n"
        "    return 0\n"
    )
    target.write_text(original_content, encoding="utf-8")

    test_file = tmp_path / "test_example.py"
    test_file.write_text(
        "from example import add\n\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    broken_code = (
        "def add(a, b):\n"
        "    return a - b\n"
    )
    provider = SequentialFakeLLMProvider(
        responses=[
            json.dumps({"content": broken_code}),
            json.dumps({"content": broken_code}),
        ]
    )

    agent = CodingAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
        max_attempts=2,
    )

    result = await agent.execute(
        {
            "task": "Fix the add function.",
            "file_path": "example.py",
        }
    )

    assert result["status"] == "tests_failed"
    assert result["attempts"] == 2
    assert provider.call_count == 2
    assert target.read_text(encoding="utf-8") == original_content


@pytest.mark.asyncio
async def test_coding_agent_removes_new_file_after_all_attempts_fail(
    tmp_path,
) -> None:
    target = tmp_path / "example.py"

    test_file = tmp_path / "test_example.py"
    test_file.write_text(
        "from example import add\n\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    broken_code = (
        "def add(a, b):\n"
        "    return a - b\n"
    )
    provider = SequentialFakeLLMProvider(
        responses=[
            json.dumps({"content": broken_code}),
            json.dumps({"content": broken_code}),
        ]
    )

    agent = CodingAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
        max_attempts=2,
    )

    result = await agent.execute(
        {
            "task": "Create the add function.",
            "file_path": "example.py",
        }
    )

    assert result["status"] == "tests_failed"
    assert result["attempts"] == 2
    assert provider.call_count == 2
    assert not target.exists()
