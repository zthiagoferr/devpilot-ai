"""Structural validator for HTML5 documents using :mod:`html.parser`.

The parser is tolerant by design, so the validator adds the checks the parser
does not enforce: document skeleton, tag balance, unique ids, image alt text,
input labels, document title, safe ``target="_blank"`` links, labeled buttons,
and repository reference resolution.
"""

from __future__ import annotations

from dataclasses import replace
from html.parser import HTMLParser

from app.languages.base import (
    Detection,
    LanguageIssue,
    ValidationContext,
    ValidationResult,
    compute_score,
)
from app.languages.references import (
    classify_reference,
    iter_html_references,
    normalize_repo_path,
)

#: Deterministic checks implemented by this validator and what it does not cover.
COVERAGE: dict[str, list[str]] = {
    "checks": [
        "structure",
        "tags",
        "attributes",
        "accessibility",
        "references",
        "document_metadata",
        "link_targets",
    ],
    "limitations": [
        "No browser or runtime analysis",
        "Structural and basic accessibility checks only; not an HTML validator",
        "Reference resolution depends on the supplied repository context",
    ],
}

_UNSAFE_TARGET_TAGS = frozenset({"a", "area"})

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

#: Open tag -> tags that implicitly close it (HTML5 optional end tags). When a
#: start tag appears whose name is in the set of the open element on top of the
#: stack, the open element is closed without requiring an explicit end tag.
_OPTIONAL_CLOSE_MAP: dict[str, frozenset[str]] = {
    "li": frozenset({"li"}),
    # <p> is closed by the next flow-content block element. Closing it when
    # those elements start avoids a false "unclosed_tag" on valid HTML5.
    "p": frozenset(
        {
            "p",
            "div",
            "ul",
            "ol",
            "li",
            "section",
            "header",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "table",
            "form",
            "hr",
            "pre",
            "blockquote",
            "address",
            "main",
            "nav",
            "aside",
            "article",
            "figure",
            "fieldset",
            "dl",
            "details",
            "dialog",
            "menu",
        }
    ),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "tr": frozenset({"tr"}),
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "option": frozenset({"option"}),
}

_UNLABELED_INPUT_TYPES = frozenset({"hidden", "submit", "button", "reset", "image"})


class HtmlValidator:
    """Perform structural checks on an HTML document."""

    language = "html"
    coverage = COVERAGE

    def validate(
        self,
        source: str,
        context: ValidationContext | None = None,
    ) -> ValidationResult:
        """Return deterministic findings for ``source``."""
        context = context or ValidationContext()
        text = source[1:] if source.startswith("\ufeff") else source
        parser = _HtmlAnalyzer(text)
        issues = [
            issue if issue.file is not None else replace(issue, file=context.path)
            for issue in parser.issues
        ]

        issues.extend(_check_references(text, context))

        issue_tuple = tuple(issues)
        if issue_tuple:
            summary = f"HTML structural checks reported {len(issue_tuple)} issue(s)."
        else:
            summary = "HTML structural checks found no issues."
        return ValidationResult(
            language=self.language,
            detection=_detection(),
            issues=issue_tuple,
            score=compute_score(issue_tuple),
            summary=summary,
            metadata={
                "validator": {
                    "name": "html_parser",
                    "official": False,
                    "disclaimer": (
                        "Structural analysis only. No browser or build tool is run."
                    ),
                },
                "coverage": dict(COVERAGE),
            },
        )


def _detection() -> Detection:
    return Detection(
        language="html",
        source="extension",
        confidence=0.99,
        reason="html_validator",
        candidates=(("html", 0.99),),
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
        language="html",
    )


class _HtmlAnalyzer(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self._source = source
        self.issues: list[LanguageIssue] = []
        self._stack: list[tuple[str, int, int]] = []
        self._saw_html = False
        self._saw_head = False
        self._saw_body = False
        self._saw_doctype = False
        self._saw_viewport = False
        self._saw_title = False
        self._open_buttons: list[dict[str, object]] = []
        self._ids: dict[str, int] = {}
        self._label_for: set[str] = set()
        self._inputs: list[dict[str, object]] = []

        self.feed(source)
        self.close()
        self._finish()

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower().startswith("doctype html"):
            self._saw_doctype = True

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._start(tag, attrs, self_closing=False)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button":
            self._close_button()
        if tag in _VOID_TAGS:
            return
        line, column = self.getpos()
        column += 1

        matching_index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index][0] == tag
            ),
            None,
        )
        if matching_index is None:
            self.issues.append(
                _issue(
                    "high",
                    f"Closing tag '</{tag}>' has no matching opening tag.",
                    "unexpected_closing_tag",
                    _context(None),
                    line,
                    column,
                )
            )
            return

        for open_tag, open_line, open_column in self._stack[matching_index + 1 :]:
            self.issues.append(
                _issue(
                    "high",
                    f"Tag '<{open_tag}>' is not closed before '</{tag}>'.",
                    "unclosed_tag",
                    _context(None),
                    open_line,
                    open_column,
                )
            )
        del self._stack[matching_index:]

    def _start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        values = {name.lower(): value for name, value in attrs}
        line, column = self.getpos()
        column += 1

        # A descendant carrying its own accessible name labels the enclosing
        # button (e.g. an icon or wrapper with aria-label).
        if tag != "button" and self._open_buttons and (
            (values.get("aria-label") or "").strip()
            or (values.get("aria-labelledby") or "").strip()
        ):
            self._open_buttons[-1]["has_content"] = True

        if tag == "html":
            self._saw_html = True
            if not (values.get("lang") or "").strip():
                self.issues.append(
                    _issue(
                        "low",
                        "The <html> element has no lang attribute.",
                        "missing_lang",
                        _context(None),
                        line,
                        column,
                    )
                )
        elif tag == "head":
            self._saw_head = True
        elif tag == "body":
            self._saw_body = True
        elif tag == "meta":
            if (values.get("name") or "").strip().lower() == "viewport":
                self._saw_viewport = True
        elif tag == "title":
            # A <title> inside <svg> names the graphic, not the document.
            if not any(entry[0] == "svg" for entry in self._stack):
                self._saw_title = True
        elif tag in _UNSAFE_TARGET_TAGS:
            self._check_link_target(tag, values, line, column)
        elif tag == "button" and not self_closing:
            self._open_buttons.append(
                {
                    "line": line,
                    "column": column,
                    "has_content": bool(
                        (values.get("aria-label") or "").strip()
                        or (values.get("aria-labelledby") or "").strip()
                        or (values.get("title") or "").strip()
                    ),
                }
            )
        elif tag == "label":
            target = (values.get("for") or "").strip()
            if target:
                self._label_for.add(target)
        elif tag == "img":
            if "alt" not in values:
                self.issues.append(
                    _issue(
                        "medium",
                        "Image is missing an alt attribute.",
                        "missing_alt",
                        _context(None),
                        line,
                        column,
                    )
                )
            elif self._open_buttons and (values.get("alt") or "").strip():
                # An icon button is labeled by the alt text of its image.
                self._open_buttons[-1]["has_content"] = True
        elif tag == "input":
            self._inputs.append(
                {
                    "attrs": values,
                    "line": line,
                    "column": column,
                    "enclosed_in_label": any(
                        entry[0] == "label" for entry in self._stack
                    ),
                }
            )

        element_id = (values.get("id") or "").strip()
        if element_id:
            if element_id in self._ids:
                self.issues.append(
                    _issue(
                        "medium",
                        f"Duplicate id '{element_id}'.",
                        "duplicate_id",
                        _context(None),
                        line,
                        column,
                    )
                )
            else:
                self._ids[element_id] = line

        # Pop every open element implicitly closed by ``tag`` (for example
        # ``<li><p>text<li>`` closes both the paragraph and the item). This
        # runs before the void-tag return so ``<hr>`` also closes ``<p>``.
        while self._stack and tag in _OPTIONAL_CLOSE_MAP.get(
            self._stack[-1][0], frozenset()
        ):
            self._stack.pop()

        if self_closing or tag in _VOID_TAGS:
            return

        self._stack.append((tag, line, column))

    def _finish(self) -> None:
        if not self._saw_doctype:
            self.issues.append(
                _issue(
                    "low",
                    "Document is missing a <!DOCTYPE html> declaration.",
                    "missing_doctype",
                    _context(None),
                    1,
                    1,
                )
            )
        if not self._saw_title:
            self.issues.append(
                _issue(
                    "low",
                    "Document has no <title> element.",
                    "missing_title",
                    _context(None),
                    1,
                    1,
                )
            )
        for tag, cause in (
            ("html", "missing_html_tag"),
            ("head", "missing_head_tag"),
            ("body", "missing_body_tag"),
        ):
            present = {
                "html": self._saw_html,
                "head": self._saw_head,
                "body": self._saw_body,
            }[tag]
            if not present:
                self.issues.append(
                    _issue(
                        "medium",
                        f"Document is missing a <{tag}> element.",
                        cause,
                        _context(None),
                        1,
                        1,
                    )
                )

        if not self._saw_viewport:
            self.issues.append(
                _issue(
                    "low",
                    "Document has no viewport meta tag.",
                    "missing_viewport",
                    _context(None),
                    1,
                    1,
                )
            )

        for tag, line, column in self._stack:
            self.issues.append(
                _issue(
                    "high",
                    f"Tag '<{tag}>' is not closed.",
                    "unclosed_tag",
                    _context(None),
                    line,
                    column,
                )
            )

        for record in self._inputs:
            self._check_input_label(record)

    def handle_data(self, data: str) -> None:
        if self._open_buttons and data.strip():
            self._open_buttons[-1]["has_content"] = True

    def _close_button(self) -> None:
        if not self._open_buttons:
            return
        record = self._open_buttons.pop()
        if record["has_content"]:
            return
        self.issues.append(
            _issue(
                "low",
                (
                    "The <button> element has no text content, aria-label, "
                    "or title."
                ),
                "button_without_label",
                _context(None),
                int(record["line"]),  # type: ignore[arg-type]
                int(record["column"]),  # type: ignore[arg-type]
            )
        )

    def _check_link_target(
        self,
        tag: str,
        values: dict[str, str | None],
        line: int,
        column: int,
    ) -> None:
        if (values.get("target") or "").strip().lower() != "_blank":
            return
        rel_tokens = {
            token
            for token in (values.get("rel") or "").lower().split()
            if token
        }
        if rel_tokens & {"noopener", "noreferrer"}:
            return
        self.issues.append(
            _issue(
                "low",
                (
                    f"<{tag}> opens a new tab (target=\"_blank\") without "
                    'rel="noopener" or rel="noreferrer".'
                ),
                "unsafe_target_blank",
                _context(None),
                line,
                column,
            )
        )

    def _check_input_label(self, record: dict[str, object]) -> None:
        attrs = record["attrs"]
        assert isinstance(attrs, dict)
        values = {str(key): value for key, value in attrs.items()}
        input_type = (values.get("type") or "text").strip().lower()
        if input_type in _UNLABELED_INPUT_TYPES:
            return
        if (values.get("aria-label") or "").strip():
            return
        if (values.get("aria-labelledby") or "").strip():
            return
        if record.get("enclosed_in_label"):
            return
        element_id = (values.get("id") or "").strip()
        if element_id and element_id in self._label_for:
            return

        self.issues.append(
            _issue(
                "medium",
                "Input element has no associated label.",
                "missing_label",
                _context(None),
                int(record["line"]),  # type: ignore[arg-type]
                int(record["column"]),  # type: ignore[arg-type]
            )
        )


def _check_references(source: str, context: ValidationContext) -> list[LanguageIssue]:
    if not context.known_paths:
        return []

    complete = context.tree_complete and not context.truncated
    issues: list[LanguageIssue] = []
    for reference in iter_html_references(source):
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


def _context(path: str | None) -> ValidationContext:
    """Internal placeholder context; file names are filled by ``_check_references``.

    Tag-level issues do not need a repository path and are left with ``file``
    unset. The public validator could inject it, but keeping the placeholder
    local avoids making the parser stateful with repository concerns.
    """
    return ValidationContext(path=path)
