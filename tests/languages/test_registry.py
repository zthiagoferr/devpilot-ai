"""Tests for validator selection and error containment."""

from __future__ import annotations

import pytest

from app.languages.base import Detection, ValidationContext
from app.languages.registry import get_validator, validate_source
import app.languages.registry as registry_module


class RaisingValidator:
    language = "javascript"

    def validate(self, source, context):
        raise RuntimeError("sensitive detail that must not be logged as a message")


def test_get_validator_returns_registered_validator() -> None:
    validator = get_validator("Python")
    assert validator.language == "python"


def test_get_validator_rejects_unknown_language() -> None:
    with pytest.raises(ValueError):
        get_validator("unknown")
    with pytest.raises(ValueError):
        get_validator("ruby")


def test_validate_source_detects_and_dispatches() -> None:
    result = validate_source("const value = 1;\n", path="app/main.js")

    assert result.language == "javascript"
    assert result.detection.language == "javascript"
    assert result.detection.source == "extension"
    assert result.metadata["validator"]["name"] == "javascript_tokenizer"
    assert result.metadata["validation_skipped"] is False
    assert result.metadata["score_status"] == "evaluated"
    coverage = result.metadata["coverage"]
    assert "delimiters" in coverage["checks"]
    assert coverage["limitations"]


def test_validate_source_uses_context_path_and_manual_language() -> None:
    context = ValidationContext(path="app/custom.prw")
    result = validate_source(
        "Return Nil\n",
        requested_language="advpl",
        context=context,
    )

    assert result.language == "advpl"
    assert result.detection.source == "manual"
    assert result.issues[0].file == "app/custom.prw"


def test_unknown_detection_is_informational() -> None:
    result = validate_source("prose without code markers", path="README")

    assert result.language == "unknown"
    assert result.metadata["validator"] is None
    assert result.metadata["validation_skipped"] is True
    assert result.metadata["score_status"] == "skipped"
    assert "coverage" not in result.metadata
    assert len(result.issues) == 1
    assert result.issues[0].severity == "info"
    assert result.issues[0].cause == "language_undetected"
    assert result.score == 100


def test_validator_error_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        registry_module,
        "get_validator",
        lambda language: RaisingValidator(),
    )
    result = validate_source("const value = 1;\n", path="app/main.js")

    assert result.language == "javascript"
    assert len(result.issues) == 1
    assert result.issues[0].cause == "validator_error"
    assert result.issues[0].severity == "warning"
    assert result.metadata["validator"] is None
    assert result.metadata["score_status"] == "unavailable"
    assert result.score == 90
    assert "coverage" not in result.metadata


def test_low_confidence_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        registry_module,
        "detect_language",
        lambda source, *, path=None, requested=None: Detection(
            language="css",
            source="content",
            confidence=0.5,
            reason="css_markers",
            candidates=(("css", 0.5),),
        ),
    )
    result = validate_source("body { color: red; }\n", path="styles/unknown")

    assert result.language == "css"
    assert result.metadata["low_confidence"] is True
    assert result.metadata["score_status"] == "partial"
    assert result.issues[0].cause == "language_low_confidence"
    assert result.issues[0].severity == "info"


def test_validators_tolerate_missing_context() -> None:
    from app.languages.validators import (
        AdvplValidator,
        CssValidator,
        HtmlValidator,
        JavascriptValidator,
        PythonValidator,
    )

    for validator in (
        AdvplValidator(),
        CssValidator(),
        HtmlValidator(),
        JavascriptValidator(),
        PythonValidator(),
    ):
        result = validator.validate("", None)
        assert result.language == validator.language


def test_every_validator_declares_its_coverage() -> None:
    from app.languages.validators import (
        AdvplValidator,
        CssValidator,
        HtmlValidator,
        JavascriptValidator,
        PythonValidator,
    )

    for validator in (
        AdvplValidator(),
        CssValidator(),
        HtmlValidator(),
        JavascriptValidator(),
        PythonValidator(),
    ):
        coverage = validator.coverage
        assert coverage["checks"], validator.language
        assert coverage["limitations"], validator.language
        result = validator.validate("", None)
        assert result.metadata["coverage"] == coverage


def test_python_coverage_declares_ast_checks() -> None:
    from app.languages.validators import PythonValidator

    coverage = PythonValidator().coverage
    assert coverage["checks"] == [
        "syntax",
        "undefined_names",
        "constant_operations",
        "literals",
        # Added for coherence: the implemented break/continue/return checks
        # were already reported but missing from the declared coverage.
        "control_flow",
    ]
    limitations = " ".join(coverage["limitations"]).lower()
    assert "heuristic" in limitations
    assert "type inference" in limitations


def test_invalid_manual_language_is_not_swallowed() -> None:
    with pytest.raises(ValueError):
        validate_source("x = 1", requested_language="ruby")
