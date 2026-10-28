"""Prompt construction and response parsing for AI corrections."""

from __future__ import annotations

import json

import pytest

from app.schemas.correction import CorrectionIssueRef
from app.services.correction_errors import CorrectionInvalidResponseError
from app.services.correction_prompt import (
    SOURCE_END,
    SOURCE_START,
    SYSTEM_PROMPT,
    build_prompt,
    parse_response,
)


def test_system_prompt_requires_json_and_forbids_execution_claims() -> None:
    lowered = SYSTEM_PROMPT.lower()

    assert "json" in lowered
    assert "corrected_code" in lowered
    assert "explanation" in lowered
    assert "complete" in lowered
    assert "never invent" in lowered or "never invent to" in lowered
    assert "compiles" in lowered


def test_build_prompt_delimits_the_source_code() -> None:
    issue = CorrectionIssueRef(
        message="Undefined variable",
        severity="high",
        line=3,
        rule_id="undefined-name",
    )

    prompt = build_prompt(
        source_code="def broken(:\n    pass\n",
        language="python",
        file="app/main.py",
        issue=issue,
        protheus_version="12.1.2410",
    )

    assert prompt.count(SOURCE_START) == 1
    assert prompt.count(SOURCE_END) == 1
    start = prompt.index(SOURCE_START) + len(SOURCE_START)
    end = prompt.index(SOURCE_END)
    assert "def broken(:" in prompt[start:end]
    assert "language: python" in prompt
    assert "file: app/main.py" in prompt
    assert "protheus_version: 12.1.2410" in prompt
    assert "undefined-name" in prompt


def test_build_prompt_marks_missing_optional_values() -> None:
    prompt = build_prompt(
        source_code="x = 1\n",
        language=None,
        file=None,
        issue=CorrectionIssueRef(message="unused"),
        protheus_version=None,
    )

    assert "language: unknown" in prompt
    assert "file: not provided" in prompt
    assert "protheus_version: not provided" in prompt


def test_parse_response_accepts_plain_json() -> None:
    payload = parse_response(
        json.dumps({"corrected_code": "x = 1\n", "explanation": "Done."}),
        max_bytes=1_000,
    )

    assert payload.corrected_code == "x = 1\n"
    assert payload.explanation == "Done."


def test_parse_response_accepts_markdown_fences_and_prose() -> None:
    content = (
        "Here is the result:\n"
        "```json\n"
        + json.dumps({"corrected_code": "y = 2\n", "explanation": "ok"})
        + "\n```\n"
    )

    payload = parse_response(content, max_bytes=1_000)

    assert payload.corrected_code == "y = 2\n"


def test_parse_response_ignores_prose_with_braces_around_the_object() -> None:
    content = (
        "Summary: use {braces} carefully } here\n"
        + json.dumps({"corrected_code": "y = 2\n", "explanation": "ok"})
        + "\nTrailing prose } with a stray brace { and more\n"
    )

    payload = parse_response(content, max_bytes=1_000)

    assert payload.corrected_code == "y = 2\n"
    assert payload.explanation == "ok"


def test_parse_response_rejects_an_oversized_explanation() -> None:
    content = json.dumps(
        {"corrected_code": "x = 1\n", "explanation": "x" * 120}
    )

    with pytest.raises(CorrectionInvalidResponseError):
        parse_response(content, max_bytes=1_000, max_explanation_bytes=100)


def test_parse_response_accepts_an_explanation_at_the_limit() -> None:
    content = json.dumps(
        {"corrected_code": "x = 1\n", "explanation": "x" * 100}
    )

    payload = parse_response(content, max_bytes=1_000, max_explanation_bytes=100)

    assert len(payload.explanation) == 100


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   ",
        "not json at all",
        "{not valid json}",
        "[]",
        json.dumps({"explanation": "missing code"}),
        json.dumps({"corrected_code": "x = 1\n"}),
        json.dumps({"corrected_code": "", "explanation": "empty code"}),
        json.dumps({"corrected_code": "x = 1\n", "explanation": "  "}),
        json.dumps({"corrected_code": 123, "explanation": "wrong type"}),
    ],
)
def test_parse_response_rejects_invalid_payloads(content: str) -> None:
    with pytest.raises(CorrectionInvalidResponseError):
        parse_response(content, max_bytes=1_000)


def test_parse_response_rejects_oversized_corrected_code() -> None:
    content = json.dumps({"corrected_code": "x" * 200, "explanation": "big"})

    with pytest.raises(CorrectionInvalidResponseError):
        parse_response(content, max_bytes=100)
