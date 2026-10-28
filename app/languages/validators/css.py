"""Structural validator for CSS3 using a small deterministic scanner.

The validator checks brace/parenthesis balance, empty selectors, duplicate
properties in a block, ``!important`` usage, ``@import`` ordering, and
repository references. It does not validate property values against the CSS
specification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.languages.base import (
    Detection,
    LanguageIssue,
    ValidationContext,
    ValidationResult,
    compute_score,
)
from app.languages.references import (
    classify_reference,
    iter_css_references,
    normalize_repo_path,
)

_PROPERTY_RE = re.compile(r"-{0,2}[A-Za-z_][\w-]*")
_IMPORTANT_RE = re.compile(r"!\s*important\b", re.IGNORECASE)


class CssValidator:
    """Perform structural checks on a CSS stylesheet."""

    language = "css"

    def validate(
        self,
        source: str,
        context: ValidationContext | None = None,
    ) -> ValidationResult:
        """Return deterministic findings for ``source``."""
        context = context or ValidationContext()
        text = source[1:] if source.startswith("\ufeff") else source
        masked = _mask_css(text)
        issues, first_brace = _scan_structure(masked, text, context)
        issues.extend(_check_references(text, context))
        issues.extend(_check_import_order(text, first_brace, context))

        issue_tuple = tuple(issues)
        if issue_tuple:
            summary = f"CSS structural checks reported {len(issue_tuple)} issue(s)."
        else:
            summary = "CSS structural checks found no issues."
        return ValidationResult(
            language=self.language,
            detection=_detection(),
            issues=issue_tuple,
            score=compute_score(issue_tuple),
            summary=summary,
            metadata={
                "validator": {
                    "name": "css_scanner",
                    "official": False,
                    "disclaimer": (
                        "Structural analysis only. No browser or build tool is run."
                    ),
                }
            },
        )


def _detection() -> Detection:
    return Detection(
        language="css",
        source="extension",
        confidence=0.99,
        reason="css_validator",
        candidates=(("css", 0.99),),
    )


@dataclass
class _Block:
    open_position: int
    segment_start: int
    is_root: bool = False
    declarations: dict[str, tuple[int, int]] = field(default_factory=dict)


def _scan_structure(
    masked: str,
    original: str,
    context: ValidationContext,
) -> tuple[list[LanguageIssue], int | None]:
    issues: list[LanguageIssue] = []
    stack: list[_Block] = [_Block(open_position=0, segment_start=0, is_root=True)]
    parentheses: list[int] = []
    first_brace: int | None = None

    for index, char in enumerate(masked):
        if char == "(":
            parentheses.append(index)
            continue
        if char == ")":
            if not parentheses:
                line, column = _line_column(original, index)
                issues.append(
                    _issue(
                        "high",
                        "Closing parenthesis has no matching opening parenthesis.",
                        "unbalanced_parentheses",
                        context,
                        line,
                        column,
                    )
                )
            else:
                parentheses.pop()
            continue

        if char == "{":
            block = stack[-1]
            prelude = masked[block.segment_start:index].strip()
            if not prelude:
                line, column = _line_column(original, index)
                issues.append(
                    _issue(
                        "high",
                        "Rule has an empty selector before '{'.",
                        "empty_selector",
                        context,
                        line,
                        column,
                    )
                )
            if first_brace is None:
                first_brace = index
            stack.append(_Block(open_position=index, segment_start=index + 1))
            continue

        if char == ";":
            if not parentheses:
                block = stack[-1]
                _finalize_declaration(block, index, masked, original, context, issues)
                block.segment_start = index + 1
            continue

        if char == "}":
            if len(stack) == 1:
                line, column = _line_column(original, index)
                issues.append(
                    _issue(
                        "critical",
                        "Closing '}' has no matching opening '{'.",
                        "unbalanced_braces",
                        context,
                        line,
                        column,
                    )
                )
                continue
            block = stack.pop()
            _finalize_declaration(block, index, masked, original, context, issues)
            stack[-1].segment_start = index + 1
            continue

    for position in parentheses:
        line, column = _line_column(original, position)
        issues.append(
            _issue(
                "high",
                "Opening parenthesis is not closed.",
                "unbalanced_parentheses",
                context,
                line,
                column,
            )
        )

    for block in stack[1:]:
        line, column = _line_column(original, block.open_position)
        issues.append(
            _issue(
                "critical",
                "Opening '{' is not closed.",
                "unbalanced_braces",
                context,
                line,
                column,
            )
        )

    for match in _IMPORTANT_RE.finditer(masked):
        line, column = _line_column(original, match.start())
        issues.append(
            _issue(
                "low",
                "Declaration uses !important.",
                "important_usage",
                context,
                line,
                column,
            )
        )

    issues.sort(key=lambda item: (item.line or 0, item.column or 0))
    return issues, first_brace


def _finalize_declaration(
    block: _Block,
    end: int,
    masked: str,
    original: str,
    context: ValidationContext,
    issues: list[LanguageIssue],
) -> None:
    segment = masked[block.segment_start:end]
    stripped = segment.strip()
    if not stripped or stripped.startswith("@") or "{" in stripped:
        return
    colon = stripped.find(":")
    if colon <= 0:
        return
    property_name = stripped[:colon].strip()
    if _PROPERTY_RE.fullmatch(property_name) is None:
        return

    leading = len(segment) - len(segment.lstrip())
    line, column = _line_column(original, block.segment_start + leading)
    key = property_name.lower()
    if key in block.declarations:
        issues.append(
            _issue(
                "medium",
                f"Property '{property_name}' is declared more than once in the same block.",
                "duplicate_property",
                context,
                line,
                column,
            )
        )
    else:
        block.declarations[key] = (line, column)


def _check_references(source: str, context: ValidationContext) -> list[LanguageIssue]:
    if not context.known_paths:
        return []

    complete = context.tree_complete and not context.truncated
    issues: list[LanguageIssue] = []
    for reference in iter_css_references(source):
        normalized = normalize_repo_path(context.path or "", reference.raw)
        target = normalized if normalized is not None else reference.raw
        classification = classify_reference(
            target,
            known_paths=context.known_paths,
            tree_complete=complete,
        )
        if classification == "missing":
            issues.append(
                _issue(
                    "high",
                    f"Referenced file '{reference.raw}' was not found in the repository tree.",
                    "reference_missing",
                    context,
                    reference.line,
                    reference.column,
                )
            )
        elif classification == "unknown":
            issues.append(
                _issue(
                    "info",
                    (
                        f"Referenced file '{reference.raw}' could not be checked "
                        "because the repository tree is incomplete."
                    ),
                    "reference_unknown",
                    context,
                    reference.line,
                    reference.column,
                )
            )
    return issues


def _check_import_order(
    source: str,
    first_brace: int | None,
    context: ValidationContext,
) -> list[LanguageIssue]:
    if first_brace is None:
        return []

    issues: list[LanguageIssue] = []
    line_starts = _line_starts(source)
    for reference in iter_css_references(source):
        if reference.kind != "import":
            continue
        if reference.line - 1 >= len(line_starts):
            continue
        offset = line_starts[reference.line - 1] + reference.column - 1
        if offset <= first_brace:
            continue
        issues.append(
            _issue(
                "medium",
                "@import is declared after style rules.",
                "import_after_rules",
                context,
                reference.line,
                reference.column,
            )
        )
    return issues


def _issue(
    severity: str,
    message: str,
    cause: str,
    context: ValidationContext,
    line: int | None = None,
    column: int | None = None,
) -> LanguageIssue:
    return LanguageIssue(
        severity=severity,  # type: ignore[arg-type]
        message=message,
        cause=cause,
        file=context.path,
        line=line,
        column=column,
        language="css",
    )


def _mask_css(source: str) -> str:
    """Mask CSS strings and comments while preserving newlines and offsets."""
    chars = list(source)
    index = 0
    length = len(source)
    quote: str | None = None

    while index < length:
        char = source[index]
        if quote is not None:
            if char == "\\" and index + 1 < length:
                chars[index] = " "
                if source[index + 1] != "\n":
                    chars[index + 1] = " "
                index += 2
                continue
            if char == quote:
                chars[index] = " "
                quote = None
                index += 1
                continue
            if char == "\n":
                quote = None
                index += 1
                continue
            chars[index] = " "
            index += 1
            continue

        if char in "\"'":
            quote = char
            chars[index] = " "
            index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            chars[index] = " "
            chars[index + 1] = " "
            index += 2
            while index + 1 < length:
                if source[index] == "*" and source[index + 1] == "/":
                    chars[index] = " "
                    chars[index + 1] = " "
                    index += 2
                    break
                if source[index] != "\n":
                    chars[index] = " "
                index += 1
            else:
                index = length
            continue
        index += 1

    return "".join(chars)


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(source):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _line_column(source: str, position: int) -> tuple[int, int]:
    line = source.count("\n", 0, position) + 1
    last_newline = source.rfind("\n", 0, position)
    return line, position - last_newline
