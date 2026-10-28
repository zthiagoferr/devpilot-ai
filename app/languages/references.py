"""Reference extraction and repository-path classification.

References are extracted with small, dependency-free scanners. The functions
never touch the filesystem: callers provide the set of paths known to exist in
the repository tree.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterator, Literal
from urllib.parse import unquote

ReferenceKind = Literal[
    "stylesheet",
    "script",
    "image",
    "import",
    "include",
    "asset",
]

_EXTERNAL_PREFIXES: tuple[str, ...] = (
    "http://",
    "https://",
    "//",
    "data:",
    "mailto:",
    "tel:",
    "javascript:",
    "blob:",
)

_PLACEHOLDER_RE = re.compile(
    r"\{\{.*?\}\}|\$\{[^}]*\}|%\([^)]*\)|<%.*?%>"
)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
#: A drive-qualified path (``C:\app.css`` or ``C:/app.css``) is not a
#: repository path; it is classified as ``unknown`` rather than ``missing``.
_WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:(?:[\\/]|$)")


@dataclass(frozen=True, slots=True)
class Reference:
    """A path referenced by a source file."""

    raw: str
    kind: ReferenceKind
    line: int
    column: int


def iter_html_references(source: str) -> Iterator[Reference]:
    """Yield references declared by ``link``, ``script``, and ``img`` tags."""
    collector = _HtmlReferenceCollector()
    collector.feed(source or "")
    collector.close()
    yield from collector.references


def iter_css_references(source: str) -> Iterator[Reference]:
    """Yield ``url(...)`` and ``@import`` references, ignoring strings/comments."""
    text = source or ""
    code = _mask_css_code(text)
    references: list[Reference] = []
    import_spans: list[tuple[int, int]] = []

    for match in re.finditer(r"(?<!\w)@import\b", code, re.IGNORECASE):
        parsed = _parse_css_import(text, match.end())
        if parsed is None:
            continue
        raw, end = parsed
        if not raw:
            continue
        line, column = _line_column(text, match.start())
        references.append(Reference(raw=raw, kind="import", line=line, column=column))
        import_spans.append((match.start(), end))

    for match in re.finditer(r"\burl\s*\(", code, re.IGNORECASE):
        if any(start <= match.start() < end for start, end in import_spans):
            continue
        parsed = _parse_css_url(text, match.end())
        if parsed is None:
            continue
        raw, _end = parsed
        if not raw:
            continue
        line, column = _line_column(text, match.start())
        references.append(Reference(raw=raw, kind="asset", line=line, column=column))

    references.sort(key=lambda item: (item.line, item.column, item.raw))
    yield from references


def iter_advpl_includes(source: str) -> Iterator[Reference]:
    """Yield ``#Include "..."`` and ``#Include <...>`` directives."""
    text = source or ""
    masked = _mask_advpl_comments(text)
    pattern = re.compile(
        r"^[ \t]*#[ \t]*include[ \t]+(?:\"(?P<quoted>[^\"]+)\"|<(?P<angle>[^>]+)>)",
        re.IGNORECASE | re.MULTILINE,
    )
    for match in pattern.finditer(masked):
        raw = match.group("quoted") or match.group("angle") or ""
        raw = raw.strip()
        if not raw:
            continue
        line, column = _line_column(text, match.start())
        yield Reference(raw=raw, kind="include", line=line, column=column)


def normalize_repo_path(source_path: str, raw: str) -> str | None:
    """Return ``raw`` as a POSIX path relative to the repository root.

    ``None`` means the reference cannot be expressed as a safe repository
    path: it is external, contains a NUL byte or a template placeholder, or
    escapes the repository through ``..``.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or "\x00" in value:
        return None
    if _PLACEHOLDER_RE.search(value):
        return None

    lowered = value.lower()
    if any(lowered.startswith(prefix) for prefix in _EXTERNAL_PREFIXES):
        return None

    path_part = value.split("#", 1)[0].split("?", 1)[0]
    if not path_part:
        return None

    decoded = unquote(path_part)
    if "\x00" in decoded or _PLACEHOLDER_RE.search(decoded):
        return None
    decoded = decoded.replace("\\", "/")
    if decoded.startswith("//") or _WINDOWS_DRIVE_RE.match(decoded):
        return None

    if decoded.startswith("/"):
        base = ""
        target = decoded.lstrip("/")
    else:
        normalized_source = (
            str(source_path or "").replace("\\", "/").lstrip("/")
        )
        base = posixpath.dirname(normalized_source)
        target = decoded

    joined = posixpath.normpath(posixpath.join(base, target))
    if joined in ("", "."):
        return None
    if joined == ".." or joined.startswith("../"):
        return None
    return joined.lstrip("/")


def classify_reference(
    target: str,
    *,
    known_paths: frozenset[str] | set[str],
    tree_complete: bool,
    is_include: bool = False,
) -> str:
    """Classify ``target`` as ``resolved``, ``missing``, ``external``, or ``unknown``.

    A path is only reported as ``missing`` when the repository tree is
    complete. Unresolved includes are always ``external`` because ADVPL include
    search paths commonly live outside the repository. Template placeholders
    (``{{...}}``, ``${...}``, ``%(...)``, ``<%...%>``), NUL bytes, and
    drive-qualified paths are ``unknown``: they cannot be resolved against the
    tree, but they are not evidence of a missing file.
    """
    if not isinstance(target, str):
        return "unknown"
    value = target.strip()
    if not value:
        return "unknown"

    lowered = value.lower()
    if lowered.startswith("#"):
        return "resolved"
    if any(lowered.startswith(prefix) for prefix in _EXTERNAL_PREFIXES):
        return "external"

    path_part = value.split("#", 1)[0].split("?", 1)[0]
    if not path_part:
        return "resolved"

    decoded = unquote(path_part).replace("\\", "/")
    if not decoded:
        return "resolved"
    if decoded.startswith("//"):
        return "external"

    # Placeholders, NUL bytes, and drive-qualified paths cannot be expressed as
    # repository paths. They are unknown (never missing), so a template such as
    # ``href="{{ base }}/style.css"`` is not reported as a missing file.
    raw_path = path_part.replace("\\", "/")
    if (
        "\x00" in value
        or "\x00" in decoded
        or _PLACEHOLDER_RE.search(value)
        or _PLACEHOLDER_RE.search(raw_path)
        or _WINDOWS_DRIVE_PATH_RE.match(value)
        or _WINDOWS_DRIVE_PATH_RE.match(raw_path)
    ):
        return "unknown"

    candidate = posixpath.normpath(decoded.lstrip("/") if decoded.startswith("/") else decoded)
    if candidate in ("", "."):
        return "resolved"
    if candidate == ".." or candidate.startswith("../"):
        return "unknown"

    known = {_clean_known_path(path) for path in known_paths}
    if candidate in known:
        return "resolved"

    if is_include:
        return "external"
    return "missing" if tree_complete else "unknown"


class _HtmlReferenceCollector(HTMLParser):
    """Collect references from parsed HTML attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[Reference] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._collect(tag, attrs)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._collect(tag, attrs)

    def _collect(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value for name, value in attrs}
        line, column = self.getpos()
        column += 1

        if tag == "link":
            href = values.get("href")
            if href:
                rel = (values.get("rel") or "").lower()
                kind: ReferenceKind = (
                    "stylesheet" if "stylesheet" in rel else "asset"
                )
                self.references.append(Reference(href, kind, line, column))
        elif tag == "script":
            src = values.get("src")
            if src:
                self.references.append(Reference(src, "script", line, column))
        elif tag == "img":
            src = values.get("src")
            if src:
                self.references.append(Reference(src, "image", line, column))
            srcset = values.get("srcset")
            if srcset:
                for raw in _parse_srcset(srcset):
                    self.references.append(Reference(raw, "image", line, column))


def _parse_srcset(value: str) -> list[str]:
    urls: list[str] = []
    for candidate in value.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        raw = candidate.split()[0]
        if raw:
            urls.append(raw)
    return urls


def _mask_css_code(source: str) -> str:
    """Mask CSS strings and comments while preserving offsets and newlines."""
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


def _parse_css_import(text: str, position: int) -> tuple[str, int] | None:
    index = _skip_css_whitespace(text, position)
    if index >= len(text):
        return None

    url_match = re.match(r"url\s*\(", text[index:], re.IGNORECASE)
    if url_match is not None:
        return _parse_css_url(text, index + url_match.end())
    if text[index] in "\"'":
        return _parse_css_string(text, index)
    return None


def _parse_css_url(text: str, content_start: int) -> tuple[str, int] | None:
    index = _skip_css_whitespace(text, content_start)
    if index >= len(text):
        return None

    if text[index] in "\"'":
        parsed = _parse_css_string(text, index)
        if parsed is None:
            return None
        raw, after_quote = parsed
        close = _skip_css_whitespace(text, after_quote)
        end = close + 1 if close < len(text) and text[close] == ")" else after_quote
        return raw, end

    start = index
    while index < len(text) and text[index] not in ")\n":
        index += 1
    raw = text[start:index].strip()
    end = index + 1 if index < len(text) and text[index] == ")" else index
    return raw, end


def _parse_css_string(text: str, quote_index: int) -> tuple[str, int] | None:
    quote = text[quote_index]
    index = quote_index + 1
    start = index
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            index += 2
            continue
        if text[index] == quote:
            return text[start:index], index + 1
        if text[index] == "\n":
            return None
        index += 1
    return None


def _skip_css_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _mask_advpl_comments(source: str) -> str:
    """Replace ADVPL comments with spaces, preserving strings and offsets."""
    chars = list(source)
    index = 0
    length = len(source)
    quote: str | None = None
    block_comment = False

    while index < length:
        char = source[index]

        if block_comment:
            if char == "*" and index + 1 < length and source[index + 1] == "/":
                chars[index] = " "
                chars[index + 1] = " "
                index += 2
                block_comment = False
                continue
            if char != "\n":
                chars[index] = " "
            index += 1
            continue

        if quote is not None:
            if char == "\\" and index + 1 < length:
                index += 2
                continue
            if char == quote:
                if index + 1 < length and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            elif char == "\n":
                quote = None
            index += 1
            continue

        if char in "\"'":
            quote = char
            index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            chars[index] = " "
            chars[index + 1] = " "
            index += 2
            block_comment = True
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            while index < length and source[index] != "\n":
                chars[index] = " "
                index += 1
            continue
        if (
            char == "*"
            or (
                char == "&"
                and index + 1 < length
                and source[index + 1] == "&"
            )
        ) and _at_line_start(source, index):
            while index < length and source[index] != "\n":
                chars[index] = " "
                index += 1
            continue
        index += 1
    return "".join(chars)


def _at_line_start(source: str, index: int) -> bool:
    cursor = index - 1
    while cursor >= 0 and source[cursor] != "\n":
        if source[cursor] not in " \t\r":
            return False
        cursor -= 1
    return True


def _clean_known_path(path: str) -> str:
    value = str(path).replace("\\", "/").lstrip("/")
    while value.startswith("./"):
        value = value[2:]
    return posixpath.normpath(value)


def _line_column(source: str, position: int) -> tuple[int, int]:
    line = source.count("\n", 0, position) + 1
    last_newline = source.rfind("\n", 0, position)
    return line, position - last_newline
