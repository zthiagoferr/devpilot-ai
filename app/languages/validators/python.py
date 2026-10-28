"""Python syntax validator used for post-correction checks.

This validator parses with :mod:`ast` only. It does not compile, import, or
execute the analyzed source, and it does not replace the ``CodeAgent``.
"""

from __future__ import annotations

import ast

from app.languages.base import (
    LanguageIssue,
    ValidationContext,
    ValidationResult,
    compute_score,
)
from app.languages.detector import Detection


class PythonValidator:
    """Check Python syntax with the standard-library AST parser."""

    language = "python"

    def __init__(self, detection: Detection | None = None) -> None:
        self._detection = detection

    def validate(
        self,
        source: str,
        context: ValidationContext | None = None,
    ) -> ValidationResult:
        """Return a critical issue when ``source`` cannot be parsed."""
        context = context or ValidationContext()
        text = source[1:] if source.startswith("\ufeff") else source
        issues: list[LanguageIssue] = []

        try:
            ast.parse(text)
        except SyntaxError as exc:
            issues.append(
                LanguageIssue(
                    severity="critical",
                    message=f"Python syntax error: {exc.msg}",
                    cause="python_syntax",
                    file=context.path,
                    line=exc.lineno,
                    column=exc.offset,
                    language=self.language,
                )
            )
        except (ValueError, TypeError) as exc:
            issues.append(
                LanguageIssue(
                    severity="critical",
                    message=f"Python source could not be parsed: {type(exc).__name__}.",
                    cause="python_syntax",
                    file=context.path,
                    language=self.language,
                )
            )

        detection = self._detection or Detection(
            language="python",
            source="extension",
            confidence=0.99,
            reason="python_validator",
            candidates=(("python", 0.99),),
        )
        issue_tuple = tuple(issues)
        if issue_tuple:
            summary = "Python syntax parsing reported an error."
        else:
            summary = "Python syntax parsing completed without errors."
        return ValidationResult(
            language=self.language,
            detection=detection,
            issues=issue_tuple,
            score=compute_score(issue_tuple),
            summary=summary,
            metadata={
                "validator": {
                    "name": "python_ast",
                    "official": False,
                    "disclaimer": (
                        "Syntax-only analysis with the standard library AST. "
                        "No code is executed."
                    ),
                }
            },
        )
