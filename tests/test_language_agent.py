"""Tests for the language-aware analysis agents."""

from __future__ import annotations

import pytest

import app.agents.language_agent as language_agent_module
from app.agents.language_agent import LanguageCodeAgent, LanguageReportAgent
from app.languages.base import Detection, ValidationResult

LANGUAGE_SAMPLES = [
    (
        "python",
        "def broken(:\n    pass\n",
        "sample.py",
        "python_syntax",
        0.99,
    ),
    (
        "advpl",
        '#Include "totvs.ch"\nUser Function X()\nLocal a := 1\nReturn a\n',
        "sample.prw",
        "include_unresolved",
        0.99,
    ),
    (
        "html",
        "<html><body><div></body></html>",
        "index.html",
        "unclosed_tag",
        0.99,
    ),
    (
        "css",
        "body { color: red; ",
        "style.css",
        "unbalanced_braces",
        0.99,
    ),
    (
        "javascript",
        "const value = ;\n",
        "app.js",
        "empty_assignment",
        0.95,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "source", "path", "cause", "confidence"), LANGUAGE_SAMPLES
)
async def test_language_code_agent_contract(
    language: str,
    source: str,
    path: str,
    cause: str,
    confidence: float,
) -> None:
    result = await LanguageCodeAgent().execute(
        {
            "project_name": "sample",
            "source_code": source,
            "file_path": path,
        }
    )

    assert result["agent"] == "language_agent"
    assert result["project_name"] == "sample"
    assert result["language"] == language
    assert result["language_source"] == "extension"
    assert result["confidence"] == confidence
    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert isinstance(result["issues"], list)
    assert isinstance(result["summary"], str) and result["summary"]
    assert isinstance(result["validator"], dict)
    assert result["validator"]["name"]
    assert result["validation_skipped"] is False
    assert result["score_status"] == "evaluated"
    assert isinstance(result["coverage"], dict)
    assert result["coverage"]["checks"]
    assert result["coverage"]["limitations"]

    assert result["issues"], language
    issue = result["issues"][0]
    assert set(issue) == {
        "severity",
        "message",
        "cause",
        "file",
        "line",
        "column",
        "language",
        "origin",
        "analysis_kind",
        "code",
        "rule_id",
    }
    assert issue["language"] == language
    assert issue["file"] == path
    assert issue["origin"] == "validator"
    assert issue["analysis_kind"] == "heuristic_validation"
    assert any(item["cause"] == cause for item in result["issues"]), result["issues"]


@pytest.mark.asyncio
async def test_language_code_agent_uses_content_detection_without_path() -> None:
    result = await LanguageCodeAgent().execute(
        {
            "project_name": "sample",
            "source_code": "const value = ;\n",
        }
    )

    assert result["language"] == "javascript"
    assert result["language_source"] == "content"
    assert 0.0 < result["confidence"] < 1.0
    assert any(issue["cause"] == "empty_assignment" for issue in result["issues"])


@pytest.mark.asyncio
async def test_language_code_agent_honors_a_supplied_manual_detection() -> None:
    detection = Detection(
        language="javascript",
        source="manual",
        confidence=1.0,
        reason="manual_request",
        candidates=(("javascript", 1.0),),
    )

    result = await LanguageCodeAgent().execute(
        {
            "project_name": "sample",
            "source_code": "const value = ;\n",
            "detection": detection,
        }
    )

    assert result["language"] == "javascript"
    assert result["language_source"] == "manual"
    assert result["confidence"] == 1.0


@pytest.mark.asyncio
async def test_language_code_agent_propagates_partial_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detection = Detection(
        language="javascript",
        source="content",
        confidence=0.5,
        reason="javascript_markers",
        candidates=(("javascript", 0.5),),
    )

    def fake_validate_source(*args, **kwargs) -> ValidationResult:
        return ValidationResult(
            language="javascript",
            detection=detection,
            issues=(),
            score=100,
            summary="Structural checks completed.",
            metadata={
                "validator": {"name": "fake"},
                "validation_skipped": False,
                "score_status": "partial",
                "coverage": {
                    "checks": ["delimiters"],
                    "limitations": ["No JavaScript engine is run"],
                },
            },
        )

    monkeypatch.setattr(language_agent_module, "validate_source", fake_validate_source)
    result = await LanguageCodeAgent().execute(
        {
            "project_name": "sample",
            "source_code": "const value = 1;\n",
            "file_path": "app.js",
        }
    )

    assert result["score_status"] == "partial"
    assert result["coverage"] == {
        "checks": ["delimiters"],
        "limitations": ["No JavaScript engine is run"],
    }


@pytest.mark.asyncio
async def test_language_code_agent_reports_unknown_language() -> None:
    result = await LanguageCodeAgent().execute(
        {
            "project_name": "sample",
            "source_code": "lorem ipsum dolor sit amet",
        }
    )

    assert result["language"] == "unknown"
    assert result["validator"] is None
    assert result["validation_skipped"] is True
    assert result["score_status"] == "skipped"
    assert result["coverage"] is None
    assert result["score"] == 100
    assert result["issues"][0]["severity"] == "info"
    assert result["issues"][0]["cause"] == "language_undetected"


@pytest.mark.asyncio
async def test_language_code_agent_echoes_requested_task() -> None:
    result = await LanguageCodeAgent().execute(
        {
            "project_name": "sample",
            "source_code": "const value = ;\n",
            "file_path": "app.js",
            "requested_task": "tests",
        }
    )

    assert result["requested_task"] == "tests"


@pytest.mark.asyncio
async def test_language_report_agent_matches_the_report_contract() -> None:
    result = await LanguageReportAgent().execute(
        {
            "project_name": "sample",
            "source_code": "const value = ;\n",
            "file_path": "app.js",
        }
    )

    assert result["agent"] == "language_report_agent"
    assert result["project_name"] == "sample"
    assert result["overall_score"] == 90
    assert result["total_issues"] == 1
    assert result["requested_task"] == "full_analysis"
    assert isinstance(result["summary"], str)
    assert "90/100" in result["summary"]

    analyses = result["analyses"]
    assert list(analyses) == ["javascript"]
    analysis = analyses["javascript"]
    assert set(analysis) == {
        "agent",
        "score",
        "issues",
        "summary",
        "language",
        "validation_skipped",
    }
    assert analysis["agent"] == "language_agent"
    assert analysis["score"] == 90
    assert analysis["language"] == "javascript"
    assert analysis["validation_skipped"] is False
    assert analysis["issues"][0]["cause"] == "empty_assignment"

    # Coverage is additive and lives at the report top level so the exact
    # ``analyses[language]`` contract above stays unchanged.
    coverage = result["coverage"]
    assert list(coverage) == ["javascript"]
    assert coverage["javascript"]["score_status"] == "evaluated"
    assert "delimiters" in coverage["javascript"]["checks"]
    assert coverage["javascript"]["limitations"]

    language = result["language"]
    assert language["language"] == "javascript"
    assert language["source"] == "extension"
    assert language["confidence"] == 0.95
    assert language["reason"]
    assert language["candidates"] == [["javascript", 0.95]]


@pytest.mark.asyncio
async def test_language_report_agent_without_issues_reports_full_score() -> None:
    result = await LanguageReportAgent().execute(
        {
            "project_name": "clean",
            "source_code": "const value = 1;\n",
            "file_path": "app.js",
        }
    )

    assert result["overall_score"] == 100
    assert result["total_issues"] == 0
    assert result["analyses"]["javascript"]["issues"] == []


@pytest.mark.asyncio
async def test_language_report_agent_flags_skipped_coverage() -> None:
    result = await LanguageReportAgent().execute(
        {
            "project_name": "unknown",
            "source_code": "lorem ipsum dolor sit amet",
        }
    )

    coverage = result["coverage"]["unknown"]
    assert coverage["score_status"] == "skipped"
    assert coverage["checks"] == []
    assert coverage["limitations"] == []
