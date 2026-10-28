"""Deterministic validator selection and error containment.

The registry is the only entry point upper layers need. It detects the
language, picks a validator, and converts unexpected validator failures into a
stable result instead of propagating an exception into the API.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from app.languages.base import (
    AUTO_CONFIDENCE_THRESHOLD,
    CANDIDATE_CONFIDENCE_FLOOR,
    SUPPORTED_LANGUAGES,
    Detection,
    LanguageIssue,
    LanguageValidator,
    UnsupportedLanguageError,
    ValidationContext,
    ValidationResult,
    compute_score,
)
from app.languages.detector import detect_language
from app.languages.validators.advpl import AdvplValidator
from app.languages.validators.css import CssValidator
from app.languages.validators.html import HtmlValidator
from app.languages.validators.javascript import JavascriptValidator
from app.languages.validators.python import PythonValidator

logger = logging.getLogger(__name__)

_VALIDATORS: dict[str, LanguageValidator] = {
    "python": PythonValidator(),
    "advpl": AdvplValidator(),
    "html": HtmlValidator(),
    "css": CssValidator(),
    "javascript": JavascriptValidator(),
}


def get_validator(language: str) -> LanguageValidator:
    """Return the validator registered for ``language``.

    Raises :class:`UnsupportedLanguageError` for ``unknown``, empty, or
    unsupported values.
    """
    if not isinstance(language, str):
        raise UnsupportedLanguageError(str(language))
    normalized = language.strip().lower()
    validator = _VALIDATORS.get(normalized)
    if validator is None:
        raise UnsupportedLanguageError(language)
    return validator


def validate_source(
    source: str,
    *,
    requested_language: str | None = None,
    path: str | None = None,
    context: ValidationContext | None = None,
) -> ValidationResult:
    """Detect and structurally validate ``source``.

    ``requested_language`` takes precedence over the path. Unknown detections
    return an informational result with ``metadata["validator"] is None``. A
    validator exception is converted into a warning issue; it never escapes
    this function. Invalid non-empty manual language values raise
    :class:`UnsupportedLanguageError`, because they indicate a caller bug
    rather than an analyzable file.
    """
    effective_context = _context_for(path, context)
    document_path = effective_context.path
    detection = detect_language(
        source,
        path=document_path,
        requested=requested_language,
    )

    if detection.language == "unknown" or detection.confidence < (
        CANDIDATE_CONFIDENCE_FLOOR
    ):
        return _unknown_result(detection, document_path)

    validator = get_validator(detection.language)
    try:
        result = validator.validate(source, effective_context)
        if not isinstance(result, ValidationResult):
            raise TypeError("Validator did not return a ValidationResult.")
    except Exception as exc:  # noqa: BLE001 - validator failures are contained
        logger.warning(
            "Language validator failed: %s",
            type(exc).__name__,
        )
        issue = LanguageIssue(
            severity="warning",
            message=(
                "The language validator could not complete the structural "
                "analysis."
            ),
            cause="validator_error",
            file=document_path,
            language=detection.language,
        )
        issues = (issue,)
        return ValidationResult(
            language=detection.language,
            detection=detection,
            issues=issues,
            score=compute_score(issues),
            summary="Structural validation could not be completed.",
            metadata={"validator": None},
        )

    result = replace(result, detection=detection)
    if (
        CANDIDATE_CONFIDENCE_FLOOR
        <= detection.confidence
        < AUTO_CONFIDENCE_THRESHOLD
    ):
        result = _flag_low_confidence(result, document_path)

    return result


def _context_for(
    path: str | None,
    context: ValidationContext | None,
) -> ValidationContext:
    if context is None:
        return ValidationContext(path=path)
    if path is not None and context.path != path:
        return replace(context, path=path)
    return context


def _unknown_result(
    detection: Detection,
    document_path: str | None,
) -> ValidationResult:
    low_confidence = (
        CANDIDATE_CONFIDENCE_FLOOR <= detection.confidence
        < AUTO_CONFIDENCE_THRESHOLD
    )
    cause = "language_low_confidence" if low_confidence else "language_undetected"
    message = (
        "Language detection confidence is too low for structural validation."
        if low_confidence
        else "Language could not be detected from the file path or content."
    )
    issue = LanguageIssue(
        severity="info",
        message=message,
        cause=cause,
        file=document_path,
        language="unknown",
    )
    issues = (issue,)
    return ValidationResult(
        language="unknown",
        detection=detection,
        issues=issues,
        score=compute_score(issues),
        summary="Language detection did not select a structural validator.",
        metadata={
            "validator": None,
            "validation_skipped": True,
            "detection_reason": detection.reason,
        },
    )


def _flag_low_confidence(
    result: ValidationResult,
    document_path: str | None,
) -> ValidationResult:
    issue = LanguageIssue(
        severity="info",
        message=(
            "Language detection confidence is low; structural findings should "
            "be reviewed."
        ),
        cause="language_low_confidence",
        file=document_path,
        language=result.language,
    )
    issues = (issue,) + tuple(result.issues)
    metadata: dict[str, Any] = dict(result.metadata)
    metadata["low_confidence"] = True
    return replace(
        result,
        issues=issues,
        score=compute_score(issues),
        metadata=metadata,
    )


__all__ = [
    "SUPPORTED_LANGUAGES",
    "UnsupportedLanguageError",
    "get_validator",
    "validate_source",
]
