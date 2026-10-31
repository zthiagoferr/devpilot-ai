"""Language contracts, detection, and deterministic structural validators."""

from __future__ import annotations

from app.languages.base import (
    AUTO_CONFIDENCE_THRESHOLD,
    CANDIDATE_CONFIDENCE_FLOOR,
    SEVERITY_WEIGHT,
    SUPPORTED_LANGUAGES,
    AnalysisKind,
    Detection,
    LanguageId,
    LanguageIssue,
    LanguageSource,
    LanguageValidator,
    Origin,
    Severity,
    UnsupportedLanguageError,
    ValidationContext,
    ValidationResult,
    compute_score,
    normalize_severity,
)
from app.languages.detector import (
    LANGUAGE_EXTENSIONS,
    detect_language,
    language_for_extension,
    supported_extensions,
)
from app.languages.references import (
    Reference,
    classify_reference,
    iter_advpl_includes,
    iter_css_references,
    iter_html_references,
    normalize_repo_path,
)
from app.languages.registry import get_validator, validate_source
from app.languages.spec import SPECS, LanguageSpec, spec_for_language

__all__ = [
    "AUTO_CONFIDENCE_THRESHOLD",
    "CANDIDATE_CONFIDENCE_FLOOR",
    "LANGUAGE_EXTENSIONS",
    "SEVERITY_WEIGHT",
    "SPECS",
    "SUPPORTED_LANGUAGES",
    "AnalysisKind",
    "Detection",
    "LanguageId",
    "LanguageIssue",
    "LanguageSource",
    "LanguageSpec",
    "LanguageValidator",
    "Origin",
    "Reference",
    "Severity",
    "UnsupportedLanguageError",
    "ValidationContext",
    "ValidationResult",
    "classify_reference",
    "compute_score",
    "detect_language",
    "get_validator",
    "iter_advpl_includes",
    "iter_css_references",
    "iter_html_references",
    "language_for_extension",
    "normalize_repo_path",
    "normalize_severity",
    "spec_for_language",
    "supported_extensions",
    "validate_source",
]
