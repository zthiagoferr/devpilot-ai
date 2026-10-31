"""Declarative specifications for every supported language.

``SPECS`` is the single source of truth for the language layer: which
extensions map to which language, the baseline detection confidence, the
validator that handles it, the coverage it declares, and the extension used
when a corrected file is exported.

The module only holds metadata. Validators remain independent and are never
rewritten here; the registry instantiates them from these specs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from app.languages.base import (
    SEVERITY_WEIGHT,
    SUPPORTED_LANGUAGES,
    LanguageValidator,
)
from app.languages.validators.advpl import AdvplValidator
from app.languages.validators.css import CssValidator
from app.languages.validators.html import HtmlValidator
from app.languages.validators.javascript import JavascriptValidator
from app.languages.validators.python import PythonValidator

_DEFAULT_WEIGHTS: Mapping[str, int] = MappingProxyType(dict(SEVERITY_WEIGHT))

#: Language -> canonical display name used by prompts and reports.
_DISPLAY_NAMES: dict[str, str] = {
    "python": "Python",
    "advpl": "ADVPL/TLPP",
    "html": "HTML",
    "css": "CSS",
    "javascript": "JavaScript",
}


@dataclass(frozen=True, slots=True)
class ScoreProfile:
    """Severity weights applied to the 100-point score.

    The default mirrors :data:`app.languages.base.SEVERITY_WEIGHT`. A language
    may declare its own profile later without changing the shared computation.
    """

    weights: Mapping[str, int] = field(default_factory=lambda: _DEFAULT_WEIGHTS)

    def weight_for(self, severity: str) -> int:
        """Return the penalty for ``severity`` (unknown severities add zero)."""
        return int(self.weights.get(severity, 0))


@dataclass(frozen=True, slots=True)
class LanguageSpec:
    """Everything the language layer needs to know about one language."""

    id: str
    display_name: str
    extensions: tuple[str, ...]
    confidence_by_extension: Mapping[str, float]
    validator: type[LanguageValidator]
    coverage: Mapping[str, list[str]]
    score_profile: ScoreProfile | None = None
    download_extension: str | None = None

    def __post_init__(self) -> None:
        if not self.extensions:
            raise ValueError(f"LanguageSpec {self.id!r} has no extensions")
        normalized = tuple(extension.lower() for extension in self.extensions)
        if any(not extension.startswith(".") for extension in normalized):
            raise ValueError(
                f"LanguageSpec {self.id!r} extensions must start with a dot"
            )
        if normalized != self.extensions:
            object.__setattr__(self, "extensions", normalized)
        missing = [
            extension
            for extension in normalized
            if extension not in self.confidence_by_extension
        ]
        if missing:
            raise ValueError(
                f"LanguageSpec {self.id!r} lacks confidence for {missing}"
            )
        if not self.coverage.get("checks") or not self.coverage.get("limitations"):
            raise ValueError(f"LanguageSpec {self.id!r} has incomplete coverage")
        if getattr(self.validator, "language", None) != self.id:
            raise ValueError(
                f"LanguageSpec {self.id!r} points at a different validator"
            )
        if self.download_extension is None:
            object.__setattr__(
                self,
                "download_extension",
                normalized[0].lstrip("."),
            )
        else:
            cleaned = self.download_extension.strip().lstrip(".")
            object.__setattr__(
                self,
                "download_extension",
                cleaned or normalized[0].lstrip("."),
            )

    def create_validator(self) -> LanguageValidator:
        """Return a new validator instance for this language."""
        return self.validator()

    def download_suffix(self) -> str:
        """Return the extension (without the dot) used for exported files."""
        return self.download_extension or self.extensions[0].lstrip(".")

    def weights(self) -> Mapping[str, int]:
        """Return the effective severity weights for this language."""
        profile = self.score_profile
        return profile.weights if profile is not None else _DEFAULT_WEIGHTS


def _spec(
    language_id: str,
    *,
    extensions: tuple[str, ...],
    confidence: Mapping[str, float],
    validator: type[LanguageValidator],
    download_extension: str,
) -> LanguageSpec:
    return LanguageSpec(
        id=language_id,
        display_name=_DISPLAY_NAMES[language_id],
        extensions=extensions,
        confidence_by_extension=confidence,
        validator=validator,
        coverage=validator.coverage,
        download_extension=download_extension,
    )


#: Ordered mapping (same order as :data:`SUPPORTED_LANGUAGES`) of language
#: specifications. The insertion order keeps detector output stable.
SPECS: dict[str, LanguageSpec] = {
    "python": _spec(
        "python",
        extensions=(".py", ".pyi"),
        confidence={".py": 0.99, ".pyi": 0.99},
        validator=PythonValidator,
        download_extension="py",
    ),
    "advpl": _spec(
        "advpl",
        extensions=(".prw", ".prg", ".ch"),
        # ``.prg`` and ``.ch`` are shared with other ecosystems and are
        # therefore less conclusive than ``.prw``.
        confidence={".prw": 0.99, ".prg": 0.75, ".ch": 0.70},
        validator=AdvplValidator,
        download_extension="prw",
    ),
    "html": _spec(
        "html",
        extensions=(".html", ".htm"),
        confidence={".html": 0.99, ".htm": 0.99},
        validator=HtmlValidator,
        download_extension="html",
    ),
    "css": _spec(
        "css",
        extensions=(".css",),
        confidence={".css": 0.99},
        validator=CssValidator,
        download_extension="css",
    ),
    "javascript": _spec(
        "javascript",
        extensions=(".js", ".mjs", ".cjs"),
        confidence={".js": 0.95, ".mjs": 0.95, ".cjs": 0.95},
        validator=JavascriptValidator,
        download_extension="js",
    ),
}


def spec_for_language(language: str | None) -> LanguageSpec | None:
    """Return the spec for ``language`` (case-insensitive) if supported."""
    if not isinstance(language, str):
        return None
    return SPECS.get(language.strip().lower())


def language_for_spec_extension(extension: str | None) -> str | None:
    """Return the language declared for an ``.ext`` string, if any."""
    if not isinstance(extension, str):
        return None
    normalized = extension.strip().lower()
    for spec in SPECS.values():
        if normalized in spec.confidence_by_extension:
            return spec.id
    return None


def download_extension_for(language: str | None) -> str | None:
    """Return the export extension (no dot) for ``language``, if supported."""
    spec = spec_for_language(language)
    return None if spec is None else spec.download_suffix()


def _validate_specs() -> None:
    """Fail fast if ``SPECS`` and the shared language list drift apart."""
    if set(SPECS) != set(SUPPORTED_LANGUAGES):
        raise RuntimeError("SPECS does not cover SUPPORTED_LANGUAGES")


_validate_specs()

__all__ = [
    "SPECS",
    "LanguageSpec",
    "ScoreProfile",
    "download_extension_for",
    "language_for_spec_extension",
    "spec_for_language",
]
