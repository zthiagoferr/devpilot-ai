"""Safety checks applied to every AI correction.

Two independent guards keep the generated text honest:

* the model must not claim that the corrected file compiles or runs, because
  nothing is executed; explicit negations ("does not compile", "não compila")
  remain allowed. Only the model's own text is checked (the explanation and the
  lines it added), never the user's pre-existing code embedded in the corrected
  file;
* new TOTVS/Protheus identifiers introduced by the model are flagged when no
  Protheus version was supplied to verify them against.

Both are textual only. No provider payload is executed.
"""

from __future__ import annotations

import re

from app.languages.base import LanguageIssue
from app.services.correction_errors import CorrectionSafetyError

#: Claims that the corrected file compiles or runs. Matched case-insensitively.
FORBIDDEN_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bcompiles?\b",
        r"\bcompiled\s+successfully\b",
        r"\bnow\s+compiles\b",
        r"\bcompila\s+corretamente\b",
        r"\bcompila\b",
        r"\bexecuta\s+com\s+sucesso\b",
        r"\bruns?\s+successfully\b",
        r"\brodou\b",
        r"\bexecutado\s+com\s+sucesso\b",
        r"\bexecutou\s+com\s+sucesso\b",
    )
)

#: A negation immediately before a claim keeps it allowed.
_NEGATION_RE = re.compile(
    r"(?:\b(?:not|never|no\s+longer|doesn'?t|does\s+not|didn'?t|did\s+not|"
    r"isn'?t|is\s+not|wasn'?t|was\s+not|cannot|can'?t|won'?t|will\s+not|"
    r"without)\b|\b(?:não|nao|nunca|jamais|sem)\b)\s*(?:[\w-]+\s*){0,3}$",
    re.IGNORECASE,
)

_CLAIM_LOOKBEHIND = 80

#: New identifiers with the usual TOTVS/Protheus prefixes.
_TOTVS_IDENTIFIER_RE = re.compile(
    r"\b(?:FW|Ms|TC|TOTVS)[A-Z0-9][A-Za-z0-9_]*\b"
)

_MAX_TOTVS_ISSUES = 20


def assert_no_execution_claims(text: str) -> None:
    """Raise :class:`CorrectionSafetyError` on a compile/run success claim."""
    if not isinstance(text, str) or not text:
        return

    for pattern in FORBIDDEN_CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - _CLAIM_LOOKBEHIND) : match.start()]
            if _NEGATION_RE.search(prefix):
                continue
            raise CorrectionSafetyError(
                "The AI correction claimed that the code compiles or runs. "
                "No code is executed by this service."
            )


def detect_unverified_totvs_usage(
    original: str,
    corrected: str,
    explanation: str,
    *,
    protheus_version: str | None,
) -> list[LanguageIssue]:
    """Return one issue per new TOTVS/Protheus identifier.

    Only identifiers absent from the original file are reported. When a
    Protheus version was supplied the caller is assumed to verify them against
    the official documentation, so nothing is flagged.
    """
    if protheus_version and str(protheus_version).strip():
        return []

    original_names = set(_TOTVS_IDENTIFIER_RE.findall(original or ""))
    corrected_names = set(_TOTVS_IDENTIFIER_RE.findall(corrected or ""))
    new_names = sorted(corrected_names - original_names)

    issues: list[LanguageIssue] = []
    for name in new_names[:_MAX_TOTVS_ISSUES]:
        issues.append(
            LanguageIssue(
                severity="low",
                message=(
                    f"The correction introduced the TOTVS/Protheus identifier "
                    f"{name!r}, which is not present in the original file. "
                    "No Protheus version was provided, so it could not be "
                    "verified against the official documentation."
                ),
                cause="unverified_totvs_api",
                origin="ai",
                analysis_kind="ia_analysis",
                code=name[:100],
            )
        )
    return issues


__all__ = [
    "FORBIDDEN_CLAIM_PATTERNS",
    "assert_no_execution_claims",
    "detect_unverified_totvs_usage",
]
