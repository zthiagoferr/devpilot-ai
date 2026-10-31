"""Tests for the declarative language specifications."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.languages.base import SEVERITY_WEIGHT, SUPPORTED_LANGUAGES
from app.languages.detector import (
    EXTENSION_CONFIDENCE,
    LANGUAGE_EXTENSIONS,
    supported_extensions,
)
from app.languages.registry import get_validator
from app.languages.spec import (
    SPECS,
    LanguageSpec,
    ScoreProfile,
    download_extension_for,
    language_for_spec_extension,
    spec_for_language,
)
from app.languages.validators.advpl import AdvplValidator

EXPECTED_EXTENSIONS: dict[str, set[str]] = {
    "python": {".py", ".pyi"},
    "advpl": {".prw", ".prg", ".ch"},
    "html": {".html", ".htm"},
    "css": {".css"},
    "javascript": {".js", ".mjs", ".cjs"},
}

EXPECTED_DOWNLOAD: dict[str, str] = {
    "python": "py",
    "advpl": "prw",
    "html": "html",
    "css": "css",
    "javascript": "js",
}


def test_every_supported_language_has_a_spec() -> None:
    assert tuple(SPECS) == SUPPORTED_LANGUAGES


def test_spec_extensions_match_the_detector_contract() -> None:
    for language, spec in SPECS.items():
        assert set(spec.extensions) == EXPECTED_EXTENSIONS[language]
        for extension in spec.extensions:
            assert LANGUAGE_EXTENSIONS[extension] == language
            assert language_for_spec_extension(extension) == language


def test_detector_tables_are_derived_from_specs() -> None:
    for language, spec in SPECS.items():
        for extension in spec.extensions:
            assert spec.confidence_by_extension[extension] == (
                EXTENSION_CONFIDENCE[extension]
            )

    declared = {
        extension for spec in SPECS.values() for extension in spec.extensions
    }
    assert declared == set(LANGUAGE_EXTENSIONS)
    assert supported_extensions() == frozenset(declared)


def test_spec_coverage_equals_the_validator_coverage() -> None:
    for language, spec in SPECS.items():
        validator = spec.create_validator()
        assert validator.language == language
        assert spec.coverage == validator.coverage

        result = validator.validate("", None)
        assert result.metadata["coverage"] == spec.coverage


def test_registry_dispatch_is_identical_to_the_specs() -> None:
    for language, spec in SPECS.items():
        validator = get_validator(language)
        assert isinstance(validator, spec.validator)
        assert validator.language == spec.id


def test_download_extension_is_available_and_stable() -> None:
    for language, expected in EXPECTED_DOWNLOAD.items():
        spec = SPECS[language]
        assert spec.download_suffix() == expected
        assert download_extension_for(language) == expected

    assert download_extension_for(None) is None
    assert download_extension_for("ruby") is None


def test_correction_export_map_is_derived_from_specs() -> None:
    from app.services.correction_diff import LANGUAGE_EXTENSIONS as EXPORT_MAP

    assert EXPORT_MAP == {
        language: spec.download_suffix() for language, spec in SPECS.items()
    }


def test_spec_lookup_is_case_insensitive() -> None:
    assert spec_for_language("  Python ") is SPECS["python"]
    assert spec_for_language("ADVPL") is SPECS["advpl"]
    assert spec_for_language(None) is None
    assert spec_for_language("ruby") is None


def test_score_profile_defaults_to_the_shared_weights() -> None:
    for spec in SPECS.values():
        assert dict(spec.weights()) == SEVERITY_WEIGHT

    profile = ScoreProfile(weights={"high": 30})
    assert profile.weight_for("high") == 30
    assert profile.weight_for("unknown") == 0


def test_specs_are_frozen() -> None:
    spec = SPECS["advpl"]

    with pytest.raises(FrozenInstanceError):
        spec.id = "other"  # type: ignore[misc]


def test_invalid_specs_are_rejected() -> None:
    with pytest.raises(ValueError):
        LanguageSpec(
            id="advpl",
            display_name="ADVPL",
            extensions=(),
            confidence_by_extension={},
            validator=AdvplValidator,
            coverage=AdvplValidator.coverage,
        )

    with pytest.raises(ValueError):
        LanguageSpec(
            id="advpl",
            display_name="ADVPL",
            extensions=(".prw",),
            confidence_by_extension={},
            validator=AdvplValidator,
            coverage=AdvplValidator.coverage,
        )

    with pytest.raises(ValueError):
        LanguageSpec(
            id="python",
            display_name="Python",
            extensions=(".prw",),
            confidence_by_extension={".prw": 0.9},
            validator=AdvplValidator,
            coverage=AdvplValidator.coverage,
        )
