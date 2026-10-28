"""Tests for the shared language contracts."""

from __future__ import annotations

from app.languages.base import (
    Detection,
    LanguageIssue,
    ValidationContext,
    compute_score,
    normalize_severity,
)


def test_normalize_severity_aliases() -> None:
    assert normalize_severity("blocker") == "critical"
    assert normalize_severity("fatal") == "critical"
    assert normalize_severity("error") == "high"
    assert normalize_severity("major") == "high"
    assert normalize_severity("warning") == "medium"
    assert normalize_severity("moderate") == "medium"
    assert normalize_severity("minor") == "low"
    assert normalize_severity("suggestion") == "info"
    assert normalize_severity("unexpected") == "info"
    assert normalize_severity(None) == "info"


def test_compute_score_uses_ui_weights_and_never_goes_negative() -> None:
    issues = [
        LanguageIssue(severity="critical", message="a", cause="a"),
        LanguageIssue(severity="medium", message="b", cause="b"),
        LanguageIssue(severity="low", message="c", cause="c"),
        LanguageIssue(severity="info", message="d", cause="d"),
    ]
    assert compute_score(issues) == 37

    many = [
        LanguageIssue(severity="critical", message=str(index), cause="critical")
        for index in range(5)
    ]
    assert compute_score(many) == 0


def test_language_issue_as_dict_is_stable() -> None:
    issue = LanguageIssue(
        severity="high",
        message="message",
        cause="cause",
        file="app.py",
        line=2,
        column=3,
        language="python",
    )
    data = issue.as_dict()

    assert data["severity"] == "high"
    assert data["cause"] == "cause"
    assert data["line"] == 2
    assert data["analysis_kind"] == "heuristic_validation"
    assert data["origin"] == "validator"


def test_validation_context_defaults_are_safe() -> None:
    context = ValidationContext()
    assert context.path is None
    assert context.known_paths == frozenset()
    assert context.tree_complete is True
    assert context.truncated is False


def test_detection_candidates_default_empty() -> None:
    detection = Detection(
        language="python",
        source="extension",
        confidence=0.99,
        reason="known_extension",
    )
    assert detection.candidates == ()
