"""Structural validator for JavaScript using a deterministic tokenizer.

The tokenizer recognizes strings, template literals, comments, and heuristic
regular-expression literals. Nothing is evaluated: no ``eval`` call is made and
the analyzed program is never executed.
"""

from __future__ import annotations

import json
import re

from app.languages.base import (
    Detection,
    LanguageIssue,
    ValidationContext,
    ValidationResult,
    compute_score,
)

_JSON_JS_MARKER = re.compile(
    r"\b(?:function|const|let|var|class|import|export|document|console|"
    r"debugger|eval)\b|=>|//|/\*",
    re.IGNORECASE,
)

_DELIMITER_PAIRS = {"(": ")", "[": "]", "{": "}"}
_CLOSING_DELIMITERS = {value: key for key, value in _DELIMITER_PAIRS.items()}
_OPENING_DELIMITERS = set(_DELIMITER_PAIRS)

_ELSE_TOKEN_RE = re.compile(r"\b(if|else)\b|[{}]")
_DECLARATION_RE = re.compile(
    r"\b(?P<kind>let|const|var|function|class)"
    r"(?:[ \t]*\*)?[ \t]+(?P<name>[A-Za-z_$][\w$]*)"
    r"|(?P<open>\{)|(?P<close>\})"
)

_DOUBLE_COMMA_RE = re.compile(r",[ \t\r\n]*,")
_EMPTY_ASSIGNMENT_RE = re.compile(r"=[ \t\r\n]*;")
_DEBUGGER_RE = re.compile(r"\bdebugger\b")
_EVAL_RE = re.compile(r"\beval[ \t\r\n]*\(")

#: Placeholder used while masking literals and comments. A non-space character
#: keeps constructs such as ``const value = `x`;`` from looking like an empty
#: assignment after their contents are removed.
_MASK_CHAR = "x"
_REGEX_KEYWORDS = frozenset(
    {
        "return",
        "case",
        "throw",
        "typeof",
        "instanceof",
        "delete",
        "void",
        "new",
        "in",
        "of",
        "yield",
        "await",
        "do",
        "else",
    }
)


class JavascriptValidator:
    """Perform structural checks on JavaScript source."""

    language = "javascript"

    def validate(
        self,
        source: str,
        context: ValidationContext | None = None,
    ) -> ValidationResult:
        """Return deterministic findings for ``source``."""
        context = context or ValidationContext()
        text = source[1:] if source.startswith("\ufeff") else source
        masked, unterminated = _mask_javascript(text)

        issues: list[LanguageIssue] = []
        for cause, message, line, column in unterminated:
            issues.append(
                _issue("high", message, cause, context, line, column)
            )

        if _is_json_only(text):
            issues.append(
                _issue(
                    "info",
                    "Source is JSON-only content without JavaScript markers.",
                    "json_only",
                    context,
                    1,
                    1,
                )
            )
            return _result(issues, context)

        issues.extend(_check_delimiters(masked, text, context))
        issues.extend(_check_else(masked, text, context))
        issues.extend(_check_declarations(masked, text, context))
        issues.extend(_check_suspicious_commas(masked, text, context))
        issues.extend(_check_debug_calls(masked, text, context))

        return _result(issues, context)


def _result(issues: list[LanguageIssue], context: ValidationContext) -> ValidationResult:
    issues.sort(key=lambda item: (item.line or 0, item.column or 0))
    issue_tuple = tuple(issues)
    if issue_tuple:
        summary = f"JavaScript structural checks reported {len(issue_tuple)} issue(s)."
    else:
        summary = "JavaScript structural checks found no issues."
    return ValidationResult(
        language="javascript",
        detection=_detection(),
        issues=issue_tuple,
        score=compute_score(issue_tuple),
        summary=summary,
        metadata={
            "validator": {
                "name": "javascript_tokenizer",
                "official": False,
                "disclaimer": (
                    "Structural analysis only. No JavaScript engine is run and "
                    "the analyzed program is not executed."
                ),
            }
        },
    )


def _detection() -> Detection:
    return Detection(
        language="javascript",
        source="extension",
        confidence=0.95,
        reason="javascript_validator",
        candidates=(("javascript", 0.95),),
    )


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
        language="javascript",
    )


def _check_delimiters(
    masked: str,
    original: str,
    context: ValidationContext,
) -> list[LanguageIssue]:
    issues: list[LanguageIssue] = []
    stack: list[tuple[str, int]] = []

    for index, char in enumerate(masked):
        if char in _OPENING_DELIMITERS:
            stack.append((char, index))
            continue
        if char not in _CLOSING_DELIMITERS:
            continue

        expected_opening = _CLOSING_DELIMITERS[char]
        if stack and stack[-1][0] == expected_opening:
            stack.pop()
            continue

        line, column = _line_column(original, index)
        issues.append(
            _issue(
                "critical",
                f"Closing delimiter '{char}' has no matching opening delimiter.",
                "unbalanced_delimiters",
                context,
                line,
                column,
            )
        )

    for opening, position in stack:
        line, column = _line_column(original, position)
        issues.append(
            _issue(
                "critical",
                f"Opening delimiter '{opening}' is not closed.",
                "unbalanced_delimiters",
                context,
                line,
                column,
            )
        )
    return issues


def _check_else(
    masked: str,
    original: str,
    context: ValidationContext,
) -> list[LanguageIssue]:
    issues: list[LanguageIssue] = []
    scopes: list[list[int]] = [[]]

    for match in _ELSE_TOKEN_RE.finditer(masked):
        token = match.group(0)
        if token == "{":
            scopes.append([])
            continue
        if token == "}":
            if len(scopes) > 1:
                scopes.pop()
            continue
        if token == "if":
            scopes[-1].append(match.start())
            continue
        if token != "else":
            continue
        if scopes[-1]:
            scopes[-1].pop()
            continue
        line, column = _line_column(original, match.start())
        issues.append(
            _issue(
                "medium",
                "Else has no matching If in the same block.",
                "orphan_else",
                context,
                line,
                column,
            )
        )
    return issues


def _check_declarations(
    masked: str,
    original: str,
    context: ValidationContext,
) -> list[LanguageIssue]:
    issues: list[LanguageIssue] = []
    scope_stack = [0]
    next_scope_id = 1
    block_bindings: dict[int, set[str]] = {0: set()}
    var_bindings: dict[int, set[str]] = {0: set()}

    for match in _DECLARATION_RE.finditer(masked):
        if match.group("open"):
            scope_stack.append(next_scope_id)
            block_bindings[next_scope_id] = set()
            var_bindings[next_scope_id] = set()
            next_scope_id += 1
            continue
        if match.group("close"):
            if len(scope_stack) > 1:
                scope_stack.pop()
            continue

        kind = (match.group("kind") or "").lower()
        name = match.group("name")
        if not kind or not name:
            continue
        scope = scope_stack[-1]
        line, column = _line_column(original, match.start())

        if kind == "var":
            if name in var_bindings[scope]:
                issues.append(
                    _issue(
                        "info",
                        f"Variable '{name}' is declared more than once with var.",
                        "redeclaration",
                        context,
                        line,
                        column,
                    )
                )
            else:
                var_bindings[scope].add(name)
            continue

        if name in block_bindings[scope]:
            issues.append(
                _issue(
                    "medium",
                    f"Binding '{name}' is declared more than once in the same block.",
                    "redeclaration",
                    context,
                    line,
                    column,
                )
            )
        else:
            block_bindings[scope].add(name)
    return issues


def _check_suspicious_commas(
    masked: str,
    original: str,
    context: ValidationContext,
) -> list[LanguageIssue]:
    issues: list[LanguageIssue] = []
    for match in _DOUBLE_COMMA_RE.finditer(masked):
        line, column = _line_column(original, match.start())
        issues.append(
            _issue(
                "medium",
                "Consecutive commas may indicate a missing element.",
                "duplicate_comma",
                context,
                line,
                column,
            )
        )
    for match in _EMPTY_ASSIGNMENT_RE.finditer(masked):
        line, column = _line_column(original, match.start())
        issues.append(
            _issue(
                "medium",
                "Assignment has no value on the right-hand side.",
                "empty_assignment",
                context,
                line,
                column,
            )
        )
    return issues


def _check_debug_calls(
    masked: str,
    original: str,
    context: ValidationContext,
) -> list[LanguageIssue]:
    issues: list[LanguageIssue] = []
    for match in _DEBUGGER_RE.finditer(masked):
        line, column = _line_column(original, match.start())
        issues.append(
            _issue(
                "low",
                "debugger statement found.",
                "debugger_statement",
                context,
                line,
                column,
            )
        )
    for match in _EVAL_RE.finditer(masked):
        line, column = _line_column(original, match.start())
        issues.append(
            _issue(
                "low",
                "eval call found.",
                "eval_usage",
                context,
                line,
                column,
            )
        )
    return issues


def _is_json_only(source: str) -> bool:
    stripped = source.lstrip("\ufeff").strip()
    if not stripped or stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
    except (ValueError, TypeError):
        return False
    return _JSON_JS_MARKER.search(stripped) is None


def _mask_javascript(source: str) -> tuple[str, list[tuple[str, str, int, int]]]:
    """Mask strings, templates, comments, and regex literals.

    Returns the masked source and a list of ``(cause, message, line, column)``
    findings for unterminated constructs.
    """
    chars = list(source)
    findings: list[tuple[str, str, int, int]] = []
    index = 0
    length = len(source)
    state = "code"
    quote: str | None = None
    start_position = 0

    while index < length:
        char = source[index]

        if state == "line_comment":
            if char == "\n":
                state = "code"
                index += 1
            else:
                chars[index] = _MASK_CHAR
                index += 1
            continue

        if state == "block_comment":
            if char == "*" and index + 1 < length and source[index + 1] == "/":
                chars[index] = _MASK_CHAR
                chars[index + 1] = _MASK_CHAR
                state = "code"
                index += 2
                continue
            if char != "\n":
                chars[index] = _MASK_CHAR
            index += 1
            continue

        if state == "string":
            if char == "\\" and index + 1 < length:
                chars[index] = _MASK_CHAR
                if source[index + 1] != "\n":
                    chars[index + 1] = _MASK_CHAR
                index += 2
                continue
            if char == quote:
                chars[index] = _MASK_CHAR
                state = "code"
                quote = None
                index += 1
                continue
            if char == "\n":
                line, column = _line_column(source, start_position)
                findings.append(
                    (
                        "unterminated_string",
                        "String literal is not terminated before the end of the line.",
                        line,
                        column,
                    )
                )
                state = "code"
                quote = None
                index += 1
                continue
            chars[index] = _MASK_CHAR
            index += 1
            continue

        if state == "template":
            if char == "\\" and index + 1 < length:
                chars[index] = _MASK_CHAR
                if source[index + 1] != "\n":
                    chars[index + 1] = _MASK_CHAR
                index += 2
                continue
            if char == "`":
                chars[index] = _MASK_CHAR
                state = "code"
                index += 1
                continue
            if char != "\n":
                chars[index] = _MASK_CHAR
            index += 1
            continue

        # Code state.
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            chars[index] = _MASK_CHAR
            chars[index + 1] = _MASK_CHAR
            state = "line_comment"
            index += 2
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            chars[index] = _MASK_CHAR
            chars[index + 1] = _MASK_CHAR
            state = "block_comment"
            start_position = index
            index += 2
            continue
        if char in "'\"":
            quote = char
            start_position = index
            state = "string"
            chars[index] = _MASK_CHAR
            index += 1
            continue
        if char == "`":
            start_position = index
            state = "template"
            chars[index] = _MASK_CHAR
            index += 1
            continue
        if char == "/" and _looks_like_regex(source, index):
            end = _find_regex_end(source, index)
            if end is not None:
                for position in range(index, end + 1):
                    if chars[position] != "\n":
                        chars[position] = _MASK_CHAR
                index = end + 1
                while index < length and source[index].isalpha():
                    chars[index] = _MASK_CHAR
                    index += 1
                continue
        index += 1

    if state == "block_comment":
        line, column = _line_column(source, start_position)
        findings.append(
            (
                "unterminated_comment",
                "Block comment is not terminated.",
                line,
                column,
            )
        )
    elif state == "template":
        line, column = _line_column(source, start_position)
        findings.append(
            (
                "unterminated_template",
                "Template literal is not terminated.",
                line,
                column,
            )
        )
    elif state == "string":
        line, column = _line_column(source, start_position)
        findings.append(
            (
                "unterminated_string",
                "String literal is not terminated.",
                line,
                column,
            )
        )

    return "".join(chars), findings


def _looks_like_regex(source: str, index: int) -> bool:
    cursor = index - 1
    while cursor >= 0 and source[cursor] in " \t\r\n":
        cursor -= 1
    if cursor < 0:
        return True

    previous = source[cursor]
    if previous in "([{=,:;!&|?+-*%^~<>":
        return True

    word_end = cursor + 1
    word_start = cursor
    while word_start >= 0 and (
        source[word_start].isalnum() or source[word_start] in "_$"
    ):
        word_start -= 1
    word = source[word_start + 1 : word_end].lower()
    return word in _REGEX_KEYWORDS


def _find_regex_end(source: str, index: int) -> int | None:
    cursor = index + 1
    length = len(source)
    in_class = False
    escaped = False

    while cursor < length and source[cursor] not in "\r\n":
        char = source[cursor]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return cursor
        cursor += 1
    return None


def _line_column(source: str, position: int) -> tuple[int, int]:
    line = source.count("\n", 0, position) + 1
    last_newline = source.rfind("\n", 0, position)
    return line, position - last_newline
