"""Bounded fields on the AI correction contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.correction import CorrectionCreate, CorrectionIssueRef


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
