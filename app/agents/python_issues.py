"""Shared enrichment for Python syntax errors reported by the legacy agents.

``CodeAgent``, ``TestAgent`` and ``DocsAgent`` historically returned only
``severity``/``message``/``line``. The extra fields below are additive: the
legacy fields keep their exact values and the serializer omits any new field
whose value is unavailable.
"""

from __future__ import annotations

from typing import Any

PYTHON_SYNTAX_CAUSE = "python_syntax"
PYTHON_SYNTAX_RULE_ID = "python_syntax_error"


def syntax_error_issue(exc: SyntaxError) -> dict[str, Any]:
    """Return the enriched issue for a Python ``SyntaxError``."""
    issue: dict[str, Any] = {
        "severity": "critical",
        "message": exc.msg,
        "line": exc.lineno,
        "cause": PYTHON_SYNTAX_CAUSE,
        "rule_id": PYTHON_SYNTAX_RULE_ID,
    }
    offset = getattr(exc, "offset", None)
    if isinstance(offset, int) and offset > 0:
        issue["column"] = offset
    return issue


__all__ = [
    "PYTHON_SYNTAX_CAUSE",
    "PYTHON_SYNTAX_RULE_ID",
    "syntax_error_issue",
]
