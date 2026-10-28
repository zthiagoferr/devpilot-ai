"""Placeholder entry point for an official ADVPL validator.

No official validator is bundled with this project yet. The integration keeps
the future contract explicit without spawning a build tool or external process.
"""

from __future__ import annotations

from typing import Any

from app.languages.base import LanguageValidator


class OfficialAdvplValidatorUnavailable(RuntimeError):
    """Raised when official ADVPL validation is enabled but not installed."""


def get_official_validator(settings: Any) -> LanguageValidator | None:
    """Return the official validator when available.

    The feature flag is read with ``getattr`` so existing settings objects and
    tests do not need to define it. While no official validator exists,
    enabling the flag fails explicitly instead of silently downgrading to the
    heuristic validator.
    """
    enabled = bool(getattr(settings, "advpl_official_validation_enabled", False))
    if not enabled:
        return None
    raise OfficialAdvplValidatorUnavailable(
        "The official ADVPL validator is not available in this build."
    )
