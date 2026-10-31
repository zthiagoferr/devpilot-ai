"""Bounded fields on the AI correction contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.correction import (
    MAX_BATCH_FILES,
    CorrectionBatchCreate,
    CorrectionBatchFile,
    CorrectionCreate,
    CorrectionIssueRef,
    PostValidationInfo,
)


def _create(**overrides) -> CorrectionCreate:
    payload = {
        "file": "src/app.py",
        "language": "python",
        "source_code": "x = 1\n",
        "issue": {"message": "unused variable", "severity": "low"},
    }
    payload.update(overrides)
    return CorrectionCreate(**payload)


def test_severity_is_bounded() -> None:
    assert CorrectionIssueRef(message="x", severity="critical").severity == "critical"

    with pytest.raises(ValidationError):
        CorrectionIssueRef(message="x", severity="s" * 21)


def test_language_is_bounded() -> None:
    assert _create(language="advpl").language == "advpl"

    with pytest.raises(ValidationError):
        _create(language="l" * 21)


def test_language_accepts_none() -> None:
    assert _create(language=None).language is None


def test_single_mode_is_default() -> None:
    request = _create()
    assert request.mode == "single"
    assert request.issue is not None


def test_full_mode_accepts_no_issue() -> None:
    request = _create(mode="full", issue=None)
    assert request.mode == "full"
    assert request.issue is None


def test_single_mode_requires_issue() -> None:
    with pytest.raises(ValidationError):
        _create(mode="single", issue=None)


def test_invalid_correction_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _create(mode="invalid")


def test_post_validation_new_fields_are_additive() -> None:
    """Legacy payloads (without the new lists) still validate."""
    legacy = {
        "status": "failed",
        "target_resolved": False,
        "issues": [],
        "summary": "legacy",
    }

    info = PostValidationInfo(**legacy)

    assert info.issues_resolved == []
    assert info.issues_remaining == []
    assert info.issues_new == []
    assert info.issues_warnings == []


def test_repository_context_is_optional_and_path_only() -> None:
    assert _create().repository_context is None

    request = _create(
        repository_context={"paths": ["totvs.ch"], "tree_complete": True},
    )

    assert request.repository_context is not None
    assert request.repository_context.paths == ["totvs.ch"]
    assert request.repository_context.tree_complete is True
    assert request.repository_context.truncated is False


def test_issue_ref_accepts_a_cause() -> None:
    issue = CorrectionIssueRef(message="x", cause="unclosed_block")

    assert issue.cause == "unclosed_block"


def test_full_mode_merges_issue_and_issues() -> None:
    """Both fields are targets: ``issue`` is never silently discarded."""
    first = CorrectionIssueRef(message="First problem", severity="medium", line=3)
    second = CorrectionIssueRef(message="Second problem", severity="high", line=7)

    request = _create(mode="full", issue=first, issues=[second])

    assert request.issues == [second, first]


def test_full_mode_does_not_duplicate_an_issue_already_in_issues() -> None:
    duplicate = CorrectionIssueRef(
        message="Image is missing an alt attribute.",
        severity="medium",
        line=5,
        cause="missing_alt",
    )

    request = _create(mode="full", issue=duplicate, issues=[duplicate.model_copy()])

    assert len(request.issues) == 1
    assert request.issues[0].line == 5


def test_full_mode_deduplicates_explicit_issues() -> None:
    """Repeated targets are collapsed so the prompt does not list them twice."""
    first = CorrectionIssueRef(message="Image is missing an alt attribute.", line=5)
    duplicate = CorrectionIssueRef(message="  image is missing an ALT attribute.  ", line=5)
    other_line = CorrectionIssueRef(message="Image is missing an alt attribute.", line=6)

    request = _create(mode="full", issue=None, issues=[first, duplicate, other_line])

    assert [issue.line for issue in request.issues] == [5, 6]


def test_single_mode_rejects_issues() -> None:
    with pytest.raises(ValidationError):
        _create(
            mode="single",
            issues=[CorrectionIssueRef(message="Second problem", line=2)],
        )


def _batch(**overrides) -> CorrectionBatchCreate:
    payload = {
        "files": [CorrectionBatchFile(path="src/app.py", source_code="x = 1\n")],
        "language": "python",
    }
    payload.update(overrides)
    return CorrectionBatchCreate(**payload)


def test_batch_files_are_capped_before_the_service_runs() -> None:
    """A hostile client cannot materialize an unbounded list of source files."""
    files = [
        CorrectionBatchFile(path=f"src/f{index}.py", source_code="x = 1\n")
        for index in range(MAX_BATCH_FILES)
    ]
    assert len(_batch(files=files).files) == MAX_BATCH_FILES

    too_many = files + [
        CorrectionBatchFile(path="src/extra.py", source_code="x = 1\n")
    ]
    with pytest.raises(ValidationError):
        _batch(files=too_many)


def test_batch_deduplicates_paths_preserving_the_first_occurrence() -> None:
    first = CorrectionBatchFile(path="src/app.py", source_code="x = 1\n")
    duplicate = CorrectionBatchFile(path="src/app.py", source_code="y = 2\n")

    request = _batch(files=[first, duplicate])

    assert len(request.files) == 1
    assert request.files[0].source_code == "x = 1\n"
