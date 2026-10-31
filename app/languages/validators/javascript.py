"""Structural validator for JavaScript using a deterministic tokenizer.

The tokenizer recognizes strings, template literals, comments, and heuristic
regular-expression literals. Nothing is evaluated: no ``eval`` call is made and
the analyzed program is never executed.

On top of the delimiter/declaration checks, the token stream feeds deliberately
conservative rules: assignment inside an ``if``/``while`` condition, loops whose
counter moves away from the condition (or ``while (true)`` without an exit),
loose equality between literal strings and numbers, ``NaN`` compared with ``==``
or ``===``, and names read without any declaration in the file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.languages.base import (
    Detection,
    LanguageIssue,
    ValidationContext,
    ValidationResult,
    compute_score,
)

#: Deterministic checks implemented by this validator and what it does not cover.
COVERAGE: dict[str, list[str]] = {
    "checks": [
        "delimiters",
        "syntax",
        "declarations",
        "control_flow",
        "conventions",
        "debug_calls",
        "conditions",
        "loops",
        "comparisons",
        "references",
    ],
    "limitations": [
        "No JavaScript engine is run",
        "No module resolution; conservative reference checks; no type inference",
        "Structural checks only; not a compiler",
    ],
}

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
    coverage = COVERAGE

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

        tokens = _tokenize(text)
        issues.extend(_check_condition_assignments(tokens, context))
        issues.extend(_check_loop_progress(tokens, context))
        issues.extend(_check_comparisons(tokens, context))
        issues.extend(_check_undeclared_references(tokens, context))

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
            },
            "coverage": dict(COVERAGE),
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


@dataclass(frozen=True, slots=True)
class _Token:
    """One lexical token produced by :func:`_tokenize`."""

    kind: str
    value: str
    line: int
    column: int


#: JavaScript reserved words (plus literals). Never treated as references.
_JS_KEYWORDS = frozenset(
    {
        "async",
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "get",
        "if",
        "import",
        "in",
        "instanceof",
        "let",
        "new",
        "null",
        "of",
        "return",
        "set",
        "static",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
    }
)

#: Names provided by the host environment. The reference check is deliberately
#: conservative, so anything that may be injected globally is whitelisted.
_JS_GLOBALS = frozenset(
    {
        "AbortController",
        "AbortSignal",
        "Array",
        "ArrayBuffer",
        "Atomics",
        "BigInt",
        "BigInt64Array",
        "BigUint64Array",
        "Blob",
        "Boolean",
        "BroadcastChannel",
        "CustomEvent",
        "DataView",
        "Date",
        "Error",
        "EvalError",
        "Event",
        "EventSource",
        "EventTarget",
        "File",
        "FileReader",
        "FinalizationRegistry",
        "Float32Array",
        "Float64Array",
        "FormData",
        "Head",
        "Headers",
        "Infinity",
        "Int16Array",
        "Int32Array",
        "Int8Array",
        "Intl",
        "JSON",
        "Map",
        "Math",
        "MutationObserver",
        "NaN",
        "Number",
        "Object",
        "Promise",
        "Proxy",
        "RangeError",
        "ReferenceError",
        "Reflect",
        "RegExp",
        "Request",
        "Response",
        "Set",
        "SharedArrayBuffer",
        "String",
        "Symbol",
        "SyntaxError",
        "TextDecoder",
        "TextEncoder",
        "TypeError",
        "URIError",
        "URL",
        "URLSearchParams",
        "Uint16Array",
        "Uint32Array",
        "Uint8Array",
        "Uint8ClampedArray",
        "WeakMap",
        "WeakRef",
        "WeakSet",
        "WebSocket",
        "Worker",
        "XMLHttpRequest",
        "__dirname",
        "__filename",
        "addEventListener",
        "alert",
        "arguments",
        "atob",
        "btoa",
        "cancelAnimationFrame",
        "clearImmediate",
        "clearInterval",
        "clearTimeout",
        "confirm",
        "console",
        "crypto",
        "decodeURI",
        "decodeURIComponent",
        "dispatchEvent",
        "document",
        "encodeURI",
        "encodeURIComponent",
        "eval",
        "exports",
        "fetch",
        "global",
        "globalThis",
        "history",
        "indexedDB",
        "isFinite",
        "isNaN",
        "localStorage",
        "location",
        "module",
        "navigator",
        "parseFloat",
        "parseInt",
        "performance",
        "process",
        "prompt",
        "queueMicrotask",
        "removeEventListener",
        "requestAnimationFrame",
        "requestIdleCallback",
        "require",
        "screen",
        "sessionStorage",
        "setImmediate",
        "setInterval",
        "setTimeout",
        "structuredClone",
        "undefined",
        "window",
    }
)

_MULTI_CHAR_OPERATORS = (
    ">>>=",
    "===",
    "!==",
    "**=",
    "<<=",
    ">>=",
    ">>>",
    "...",
    "=>",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "??",
    "?.",
    "++",
    "--",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "**",
    "<<",
    ">>",
)

_IDENTIFIER_TOKEN_RE = re.compile(r"[$A-Za-z_\u0080-\uffff][$\w\u0080-\uffff]*")
_NUMBER_TOKEN_RE = re.compile(
    r"(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d+)?n?"
)

_ASSIGNMENT_OPERATORS = frozenset(
    {
        "=",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "**=",
        "&&=",
        "||=",
        "??=",
        "&=",
        "|=",
        "^=",
        "<<=",
        ">>=",
        ">>>=",
        "++",
        "--",
    }
)

_DECLARATION_KEYWORDS = frozenset({"let", "const", "var"})

#: Contextual keywords and property-ish names that must never be mistaken for
#: free-variable reads (``import x from``/``export { a as b }``/accessors).
_CONTEXTUAL_KEYWORDS = frozenset({"from", "as", "get", "set", "static"})

#: Keywords that may precede a method shorthand inside an object or class body.
_METHOD_PREFIXES = frozenset({"get", "set", "static", "async", "*"})

_CONDITION_LITERAL_TRUTHY = frozenset({"true", "1"})

_SEVERITY_ASSIGNMENT_IN_CONDITION = "high"
_SEVERITY_LOOP_WITHOUT_PROGRESS = "medium"
_SEVERITY_SUSPICIOUS_EQUALITY = "low"
_SEVERITY_NAN_COMPARISON = "medium"
_SEVERITY_UNDECLARED_REFERENCE = "medium"


def _tokenize(source: str) -> list[_Token]:
    """Split ``source`` into tokens, skipping comments and literal contents.

    Strings, template literals, and regular expressions become single opaque
    tokens, so their contents are never mistaken for identifiers or operators.
    """
    tokens: list[_Token] = []
    index = 0
    length = len(source)
    line = 1
    column = 1

    while index < length:
        char = source[index]

        if char == "\n":
            index += 1
            line += 1
            column = 1
            continue
        if char in " \t\r\f\v":
            index += 1
            column += 1
            continue

        start_line = line
        start_column = column

        if char == "/" and index + 1 < length and source[index + 1] == "/":
            while index < length and source[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            index += 2
            while index < length:
                if (
                    source[index] == "*"
                    and index + 1 < length
                    and source[index + 1] == "/"
                ):
                    index += 2
                    break
                if source[index] == "\n":
                    line += 1
                    column = 1
                else:
                    column += 1
                index += 1
            continue

        if char in "'\"":
            value, index, line, column = _read_quoted(source, index, line, column)
            tokens.append(_Token("string", value, start_line, start_column))
            continue

        if char == "`":
            value, index, line, column = _read_template(source, index, line, column)
            tokens.append(_Token("template", value, start_line, start_column))
            continue

        if char == "/" and _looks_like_regex(source, index):
            end = _find_regex_end(source, index)
            if end is not None:
                value = source[index : end + 1]
                column += end + 1 - index
                index = end + 1
                while index < length and source[index].isalpha():
                    value += source[index]
                    column += 1
                    index += 1
                tokens.append(_Token("regex", value, start_line, start_column))
                continue

        number_match = _NUMBER_TOKEN_RE.match(source, index)
        if number_match is not None:
            value = number_match.group(0)
            tokens.append(_Token("number", value, start_line, start_column))
            column += len(value)
            index += len(value)
            continue

        identifier_match = _IDENTIFIER_TOKEN_RE.match(source, index)
        if identifier_match is not None:
            value = identifier_match.group(0)
            tokens.append(_Token("identifier", value, start_line, start_column))
            column += len(value)
            index += len(value)
            continue

        operator = next(
            (
                candidate
                for candidate in _MULTI_CHAR_OPERATORS
                if source.startswith(candidate, index)
            ),
            None,
        )
        if operator is not None:
            tokens.append(_Token("operator", operator, start_line, start_column))
            column += len(operator)
            index += len(operator)
            continue

        tokens.append(_Token("punctuation", char, start_line, start_column))
        index += 1
        column += 1

    return tokens


def _read_quoted(
    source: str,
    index: int,
    line: int,
    column: int,
) -> tuple[str, int, int, int]:
    """Return the raw body of the string literal starting at ``index``."""
    quote = source[index]
    cursor = index + 1
    body: list[str] = []
    line_value = line
    column_value = column + 1
    length = len(source)

    while cursor < length:
        char = source[cursor]
        if char == "\\" and cursor + 1 < length:
            body.append(source[cursor : cursor + 2])
            if source[cursor + 1] == "\n":
                line_value += 1
                column_value = 1
            else:
                column_value += 2
            cursor += 2
            continue
        if char == quote:
            return "".join(body), cursor + 1, line_value, column_value + 1
        if char == "\n":
            line_value += 1
            column_value = 1
            cursor += 1
            continue
        body.append(char)
        column_value += 1
        cursor += 1

    return "".join(body), cursor, line_value, column_value


def _read_template(
    source: str,
    index: int,
    line: int,
    column: int,
) -> tuple[str, int, int, int]:
    """Return the raw body of the template literal starting at ``index``."""
    cursor = index + 1
    body: list[str] = []
    line_value = line
    column_value = column + 1
    length = len(source)

    while cursor < length:
        char = source[cursor]
        if char == "\\" and cursor + 1 < length:
            body.append(source[cursor : cursor + 2])
            if source[cursor + 1] == "\n":
                line_value += 1
                column_value = 1
            else:
                column_value += 2
            cursor += 2
            continue
        if char == "`":
            return "".join(body), cursor + 1, line_value, column_value + 1
        if char == "\n":
            body.append(char)
            line_value += 1
            column_value = 1
            cursor += 1
            continue
        body.append(char)
        column_value += 1
        cursor += 1

    return "".join(body), cursor, line_value, column_value


def _matching_delimiter(tokens: list[_Token], open_index: int) -> int | None:
    """Return the index of the delimiter closing ``tokens[open_index]``."""
    opening = tokens[open_index].value
    closing = _DELIMITER_PAIRS.get(opening)
    if closing is None:
        return None

    depth = 0
    for index in range(open_index, len(tokens)):
        value = tokens[index].value
        if value == opening:
            depth += 1
        elif value == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_top_level(
    tokens: list[_Token],
    start: int,
    end: int,
    separator: str,
) -> list[list[_Token]]:
    """Split ``tokens[start:end]`` on ``separator`` at nesting depth zero."""
    segments: list[list[_Token]] = [[]]
    depth = 0
    for index in range(start, end):
        token = tokens[index]
        value = token.value
        if value in _OPENING_DELIMITERS:
            depth += 1
        elif value in _CLOSING_DELIMITERS:
            depth -= 1
        elif depth == 0 and value == separator:
            segments.append([])
            continue
        segments[-1].append(token)
    return segments


def _find_top_level(segment: list[_Token], values: frozenset[str]) -> int | None:
    depth = 0
    for index, token in enumerate(segment):
        value = token.value
        if value in _OPENING_DELIMITERS:
            depth += 1
            continue
        if value in _CLOSING_DELIMITERS:
            depth -= 1
            continue
        if depth == 0 and value in values:
            return index
    return None


def _simple_identifier(segment: list[_Token], position: int) -> str | None:
    """Return a plain identifier at ``position`` (not a member/keyword)."""
    if position < 0 or position >= len(segment):
        return None
    token = segment[position]
    if token.kind != "identifier" or token.value in _JS_KEYWORDS:
        return None
    if position > 0 and segment[position - 1].value in {".", "?."}:
        return None
    return token.value


def _check_condition_assignments(
    tokens: list[_Token],
    context: ValidationContext,
) -> list[LanguageIssue]:
    """Report ``if (x = value)``/``while (x = value)`` (likely ``===``)."""
    issues: list[LanguageIssue] = []
    for index, token in enumerate(tokens):
        if token.kind != "identifier" or token.value not in {"if", "while"}:
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].value != "(":
            continue
        close_index = _matching_delimiter(tokens, index + 1)
        if close_index is None:
            continue

        depth = 0
        for position in range(index + 2, close_index):
            current = tokens[position]
            if current.value in _OPENING_DELIMITERS:
                depth += 1
                continue
            if current.value in _CLOSING_DELIMITERS:
                depth -= 1
                continue
            if depth != 0 or current.value != "=":
                continue

            previous = tokens[position - 1]
            if previous.kind != "identifier" or previous.value in _JS_KEYWORDS:
                continue
            # Plain ``x = value`` only: member assignments are out of scope.
            if position >= 2 and tokens[position - 2].value in {".", "?."}:
                continue
            issues.append(
                _issue(
                    _SEVERITY_ASSIGNMENT_IN_CONDITION,
                    (
                        f"Assignment to '{previous.value}' inside a condition; "
                        "'=' was probably intended as a comparison."
                    ),
                    "assignment_in_condition",
                    context,
                    current.line,
                    current.column,
                )
            )
    return issues


def _check_loop_progress(
    tokens: list[_Token],
    context: ValidationContext,
) -> list[LanguageIssue]:
    """Report loops whose update moves the counter away from the condition."""
    issues: list[LanguageIssue] = []
    for index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        if token.value == "for":
            issue = _for_loop_without_progress(tokens, index, context)
        elif token.value == "while":
            issue = _while_constant_without_exit(tokens, index, context)
        else:
            continue
        if issue is not None:
            issues.append(issue)
    return issues


def _for_loop_without_progress(
    tokens: list[_Token],
    index: int,
    context: ValidationContext,
) -> LanguageIssue | None:
    open_index = index + 1
    if open_index >= len(tokens) or tokens[open_index].value != "(":
        return None
    close_index = _matching_delimiter(tokens, open_index)
    if close_index is None:
        return None

    segments = _split_top_level(tokens, open_index + 1, close_index, ";")
    if len(segments) != 3:
        return None

    condition = segments[1]
    update = segments[2]
    comparison_index = _find_top_level(
        condition, frozenset({"<", "<=", ">", ">="})
    )
    if comparison_index is None:
        return None

    operator = condition[comparison_index].value
    left_name = _simple_identifier(condition, comparison_index - 1)
    right_name = _simple_identifier(condition, comparison_index + 1)

    counter: str | None = None
    step: int | None = None
    on_left = False
    for candidate, is_left in ((left_name, True), (right_name, False)):
        if candidate is None:
            continue
        candidate_step = _loop_update_step(update, candidate)
        if candidate_step is None:
            continue
        counter, step, on_left = candidate, candidate_step, is_left
        break

    if counter is None or step is None:
        return None

    # ``i < n`` needs ``i`` to grow; ``n > i`` needs ``i`` to grow as well.
    increasing = operator in {"<", "<="} if on_left else operator in {">", ">="}
    expected_direction = 1 if increasing else -1
    if step == expected_direction:
        return None

    keyword = tokens[index]
    return _issue(
        _SEVERITY_LOOP_WITHOUT_PROGRESS,
        (
            f"'for' loop updates '{counter}' in the opposite direction of its "
            f"condition ('{operator}'), so it never makes progress."
        ),
        "loop_without_progress",
        context,
        keyword.line,
        keyword.column,
    )


def _loop_update_step(update: list[_Token], counter: str) -> int | None:
    """Return +1/-1 for the counter update, or ``None`` when undetermined."""
    for position, token in enumerate(update):
        if token.value in {"++", "--"}:
            name = _simple_identifier(update, position - 1) or _simple_identifier(
                update, position + 1
            )
            if name == counter:
                return 1 if token.value == "++" else -1
        elif token.value in {"+=", "-="}:
            name = _simple_identifier(update, position - 1)
            if name == counter:
                return 1 if token.value == "+=" else -1
    return None


def _while_constant_without_exit(
    tokens: list[_Token],
    index: int,
    context: ValidationContext,
) -> LanguageIssue | None:
    open_index = index + 1
    if open_index >= len(tokens) or tokens[open_index].value != "(":
        return None
    close_index = _matching_delimiter(tokens, open_index)
    if close_index is None:
        return None

    condition = [token.value for token in tokens[open_index + 1 : close_index]]
    if len(condition) != 1 or condition[0] not in _CONDITION_LITERAL_TRUTHY:
        return None

    body_start = close_index + 1
    if body_start >= len(tokens):
        return None

    if tokens[body_start].value == "{":
        body_end = _matching_delimiter(tokens, body_start)
        if body_end is None:
            return None
        body = tokens[body_start + 1 : body_end]
    else:
        cursor = body_start
        while cursor < len(tokens) and tokens[cursor].value != ";":
            cursor += 1
        body = tokens[body_start:cursor]

    if any(
        token.kind == "identifier" and token.value in {"break", "return", "throw"}
        for token in body
    ):
        return None

    keyword = tokens[index]
    return _issue(
        _SEVERITY_LOOP_WITHOUT_PROGRESS,
        "While loop has a constant true condition and no break or return.",
        "loop_without_progress",
        context,
        keyword.line,
        keyword.column,
    )


def _check_comparisons(
    tokens: list[_Token],
    context: ValidationContext,
) -> list[LanguageIssue]:
    """Report comparisons that are provably wrong from literals alone."""
    issues: list[LanguageIssue] = []
    for index, token in enumerate(tokens):
        if token.kind != "operator" or token.value not in {"==", "==="}:
            continue
        if index == 0 or index + 1 >= len(tokens):
            continue
        left = tokens[index - 1]
        right = tokens[index + 1]

        if _is_nan(left) or _is_nan(right):
            issues.append(
                _issue(
                    _SEVERITY_NAN_COMPARISON,
                    (
                        "NaN is never equal to any value, including itself; "
                        "the comparison always evaluates to false."
                    ),
                    "nan_comparison",
                    context,
                    token.line,
                    token.column,
                )
            )
            continue

        if token.value != "==":
            continue
        kinds = {_literal_kind(left), _literal_kind(right)}
        if kinds == {"string", "number"}:
            issues.append(
                _issue(
                    _SEVERITY_SUSPICIOUS_EQUALITY,
                    (
                        "Loose equality between a string literal and a number "
                        "literal relies on type coercion."
                    ),
                    "suspicious_loose_equality",
                    context,
                    token.line,
                    token.column,
                )
            )
    return issues


def _is_nan(token: _Token) -> bool:
    return token.kind == "identifier" and token.value == "NaN"


def _literal_kind(token: _Token) -> str | None:
    if token.kind == "string":
        return "string"
    if token.kind == "number":
        return "number"
    return None


def _declared_names(tokens: list[_Token]) -> tuple[set[str], bool]:
    """Collect names bound anywhere in the file.

    Returns ``(names, has_destructuring)``. When a destructuring pattern is
    present the caller skips the reference check, because this collector
    intentionally does not model patterns.
    """
    declared: set[str] = set()
    has_destructuring = False

    for index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if token.value in _DECLARATION_KEYWORDS:
            if following is None:
                continue
            if following.value in {"{", "["}:
                has_destructuring = True
            elif following.kind == "identifier":
                declared.add(following.value)
        elif token.value in {"function", "class"}:
            if following is not None and following.kind == "identifier":
                declared.add(following.value)
        elif token.value == "import":
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor].value not in {
                "from",
                ";",
                "(",
            }:
                if tokens[cursor].kind == "identifier":
                    declared.add(tokens[cursor].value)
                cursor += 1
        elif token.value == "export":
            # ``export { a, b }`` re-exports names that may be declared in
            # another module, so they are not free-variable reads here.
            if index + 1 < len(tokens) and tokens[index + 1].value == "{":
                end = _matching_delimiter(tokens, index + 1)
                if end is not None:
                    declared |= _identifiers_between(tokens, index + 2, end)

    declared |= _parameter_names(tokens)
    return declared, has_destructuring


def _parameter_names(tokens: list[_Token]) -> set[str]:
    """Collect names bound by parameters and method definitions."""
    names: set[str] = set()
    for index, token in enumerate(tokens):
        if token.kind == "operator" and token.value == "=>":
            previous = tokens[index - 1] if index > 0 else None
            if previous is None:
                continue
            if previous.kind == "identifier":
                names.add(previous.value)
            elif previous.value == ")":
                open_index = _opening_delimiter(tokens, index - 1)
                if open_index is not None:
                    names |= _identifiers_between(tokens, open_index + 1, index - 1)
            continue
        if token.kind != "identifier":
            continue

        if token.value == "function":
            cursor = index + 1
            if cursor < len(tokens) and tokens[cursor].kind == "identifier":
                cursor += 1
            if cursor < len(tokens) and tokens[cursor].value == "(":
                end = _matching_delimiter(tokens, cursor)
                if end is not None:
                    names |= _identifiers_between(tokens, cursor + 1, end)
        elif token.value == "catch":
            cursor = index + 1
            if cursor < len(tokens) and tokens[cursor].value == "(":
                end = _matching_delimiter(tokens, cursor)
                if end is not None:
                    names |= _identifiers_between(tokens, cursor + 1, end)
        elif index + 1 < len(tokens) and tokens[index + 1].value == "(":
            if not _is_method_definition(tokens, index):
                continue
            end = _matching_delimiter(tokens, index + 1)
            if end is not None and end + 1 < len(tokens):
                if tokens[end + 1].value == "{":
                    # The method name is a property of the enclosing object or
                    # class, so references to it are not free-variable reads.
                    names.add(token.value)
                    names |= _identifiers_between(tokens, index + 2, end)
    return names


def _is_method_definition(tokens: list[_Token], index: int) -> bool:
    """Heuristic: ``name(params) {}`` inside an object/class body."""
    if index == 0:
        return False
    previous = tokens[index - 1]
    if previous.value in {".", "?."} or previous.kind == "string":
        return False
    if previous.value in {"{", "}", ",", ";", "*"}:
        return True
    return previous.value in _METHOD_PREFIXES


def _opening_delimiter(tokens: list[_Token], close_index: int) -> int | None:
    opening = _CLOSING_DELIMITERS.get(tokens[close_index].value)
    if opening is None:
        return None
    depth = 0
    for index in range(close_index, -1, -1):
        value = tokens[index].value
        if value == tokens[close_index].value:
            depth += 1
        elif value == opening:
            depth -= 1
            if depth == 0:
                return index
    return None


def _identifiers_between(
    tokens: list[_Token],
    start: int,
    end: int,
) -> set[str]:
    names: set[str] = set()
    for index in range(start, end):
        token = tokens[index]
        if token.kind != "identifier" or token.value in _JS_KEYWORDS:
            continue
        if index > 0 and tokens[index - 1].value in {".", "?.", "#"}:
            continue
        names.add(token.value)
    return names


def _check_undeclared_references(
    tokens: list[_Token],
    context: ValidationContext,
) -> list[LanguageIssue]:
    """Report identifiers whose first occurrence is a read and never bound.

    The check is conservative on purpose: a name is reported only when it is
    not declared anywhere in the file, is not a known global, and its first
    occurrence is not a write. Destructured declarations disable the check.
    """
    declared, has_destructuring = _declared_names(tokens)
    if has_destructuring:
        return []

    issues: list[LanguageIssue] = []
    seen: set[str] = set()

    for index, token in enumerate(tokens):
        if token.kind != "identifier" or token.value in seen:
            continue
        name = token.value
        if name in _JS_KEYWORDS or name in _JS_GLOBALS or name in declared:
            continue
        if name in _CONTEXTUAL_KEYWORDS:
            continue
        seen.add(name)
        if not _is_read_position(tokens, index):
            continue
        issues.append(
            _issue(
                _SEVERITY_UNDECLARED_REFERENCE,
                (
                    f"Name '{name}' is read but never declared in this file and "
                    "is not a known global."
                ),
                "undeclared_reference",
                context,
                token.line,
                token.column,
            )
        )
    return issues


def _is_read_position(tokens: list[_Token], index: int) -> bool:
    """Return ``True`` when ``tokens[index]`` is clearly read, not bound."""
    previous = tokens[index - 1] if index > 0 else None
    following = tokens[index + 1] if index + 1 < len(tokens) else None

    if previous is not None:
        if previous.value in {".", "?.", "#"}:
            return False
        if previous.value in _DECLARATION_KEYWORDS | {"function", "class", "import"}:
            return False
        if previous.value in {"typeof", "break", "continue", "as"}:
            return False

    if following is not None:
        if following.value in _ASSIGNMENT_OPERATORS:
            return False
        if following.value in {":", "of", "in", "as"}:
            return False
        if following.value == "(" and previous is not None:
            if previous.value in {"{", "}", ",", ";", "*"}:
                return False

    return True


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
