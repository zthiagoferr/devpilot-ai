import json
import re

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


def _repository_context(prompt: str) -> str:
    marker = "Relevant repository context"
    assert marker in prompt
    return prompt.split(marker, 1)[1]


def _context_file_contents(context: str) -> list[str]:
    matches = re.findall(
        r"(?:^|\n)File: [^\n]+\n(.*?)(?=\nFile: |\Z)",
        context,
        flags=re.DOTALL,
    )
    return matches


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


@pytest.mark.asyncio
async def test_coding_agent_includes_relevant_safe_repository_files_in_prompt(
    tmp_path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text(
        "from helper import increment\n\n"
        "def calculate(value):\n"
        "    return increment(value)\n",
        encoding="utf-8",
    )
    (tmp_path / "helper.py").write_text(
        "def increment(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "The example module uses helper.increment.\n",
        encoding="utf-8",
    )
    (tmp_path / "test_example.py").write_text(
        "from example import calculate\n\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )

    provider = FakeLLMProvider(
        response=json.dumps({"content": target.read_text(encoding="utf-8")}),
        model="fake-model",
    )
    agent = CodingAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
    )

    await agent.execute({"task": "Improve calculate.", "file_path": "example.py"})

    assert provider.last_prompt is not None
    assert "File: helper.py" in provider.last_prompt
    assert "def increment(value):" in provider.last_prompt
    assert "The example module uses helper.increment." in provider.last_prompt


@pytest.mark.asyncio
async def test_coding_agent_does_not_duplicate_target_in_repository_context(
    tmp_path,
) -> None:
    target_content = (
        "TARGET_UNIQUE_CONTENT = 'only in the target section'\n"
    )
    target = tmp_path / "example.py"
    target.write_text(target_content, encoding="utf-8")
    (tmp_path / "test_example.py").write_text(
        "def test_placeholder():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    provider = FakeLLMProvider(
        response=json.dumps({"content": target_content}),
        model="fake-model",
    )
    agent = CodingAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
    )

    await agent.execute({"task": "Review the file.", "file_path": "example.py"})

    assert provider.last_prompt is not None
    context = _repository_context(provider.last_prompt)
    assert "File: example.py" not in context
    assert target_content not in context


@pytest.mark.asyncio
async def test_coding_agent_never_includes_sensitive_env_content(
    tmp_path,
) -> None:
    secret = "TEST_ONLY_FAKE_SECRET_DO_NOT_INCLUDE"
    (tmp_path / ".env").write_text(
        f"API_KEY={secret}\n",
        encoding="utf-8",
    )
    target = tmp_path / "example.py"
    target.write_text("def value():\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_example.py").write_text(
        "from example import value\n\n"
        "def test_value():\n"
        "    assert value() == 1\n",
        encoding="utf-8",
    )

    provider = FakeLLMProvider(
        response=json.dumps({"content": target.read_text(encoding="utf-8")}),
        model="fake-model",
    )
    agent = CodingAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
    )

    await agent.execute({"task": "Inspect the project.", "file_path": "example.py"})

    assert provider.last_prompt is not None
    assert secret not in provider.last_prompt
    assert "API_KEY=" not in provider.last_prompt


@pytest.mark.asyncio
async def test_coding_agent_limits_repository_context_to_eight_related_files(
    tmp_path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text("def value():\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_example.py").write_text(
        "from example import value\n\n"
        "def test_value():\n"
        "    assert value() == 1\n",
        encoding="utf-8",
    )
    for index in range(12):
        (tmp_path / f"related_{index}.py").write_text(
            f"RELATED_FILE_{index} = {index}\n",
            encoding="utf-8",
        )

    provider = FakeLLMProvider(
        response=json.dumps({"content": target.read_text(encoding="utf-8")}),
        model="fake-model",
    )
    agent = CodingAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
    )

    await agent.execute({"task": "Inspect related code.", "file_path": "example.py"})

    assert provider.last_prompt is not None
    context = _repository_context(provider.last_prompt)
    assert len(re.findall(r"(?:^|\n)File: [^\n]+", context)) <= 8


@pytest.mark.asyncio
async def test_coding_agent_bounds_related_repository_content_to_twelve_thousand_chars(
    tmp_path,
) -> None:
    target = tmp_path / "example.py"
    target.write_text("def value():\n    return 1\n", encoding="utf-8")
    (tmp_path / "test_example.py").write_text(
        "from example import value\n\n"
        "def test_value():\n"
        "    assert value() == 1\n",
        encoding="utf-8",
    )
    for index in range(10):
        (tmp_path / f"large_related_{index}.py").write_text(
            (f"RELATED_{index}_" + "x" * 1990) + "\n",
            encoding="utf-8",
        )

    provider = FakeLLMProvider(
        response=json.dumps({"content": target.read_text(encoding="utf-8")}),
        model="fake-model",
    )
    agent = CodingAgent(
        llm_service=LLMService(provider),
        project_root=tmp_path,
    )

    await agent.execute({"task": "Inspect large related files.", "file_path": "example.py"})

    assert provider.last_prompt is not None
    contents = _context_file_contents(_repository_context(provider.last_prompt))
    assert sum(len(content) for content in contents) <= 12000
