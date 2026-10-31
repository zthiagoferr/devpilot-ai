"""Structural validator for CSS3 using a small deterministic scanner.

The validator checks brace/parenthesis balance, empty selectors, duplicate
properties in a block, ``!important`` usage, ``@import`` ordering, and
repository references. It also validates property names and values against a
curated subset of the specification: unknown properties are reported as
``unknown_property``, colors are checked for every color/paint property
(hexadecimal, color functions, and the 148 named colors), and units are checked
against the type expected by the property (``invalid_unit``).

Values that cannot be resolved statically are always accepted: CSS-wide
keywords, custom properties (``--*``), and the ``var()``/``env()``/``calc()``/
``clamp()``/``min()``/``max()``/``url()`` functions.
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

#: Deterministic checks implemented by this validator and what it does not cover.
COVERAGE: dict[str, list[str]] = {
    "checks": [
        "structure",
        "delimiters",
        "selectors",
        "declarations",
        "conventions",
        "imports",
        "references",
        "property_names",
        "value_types",
        "colors",
        "units",
    ],
    "limitations": [
        "No browser or runtime analysis",
        (
            "Property names and values are checked against a curated subset of "
            "the specification; custom properties and var()/calc() are not resolved"
        ),
        "Structural checks only; not a CSS validator",
    ],
}

_PROPERTY_RE = re.compile(r"-{0,2}[A-Za-z_][\w-]*")
_IMPORTANT_RE = re.compile(r"!\s*important\b", re.IGNORECASE)

#: Value categories used by the curated property table.
_COLOR = "color"
_PAINT = "paint"
_LENGTH = "length"
_LENGTH_PERCENTAGE = "length-percentage"
_TIME = "time"
_ANGLE = "angle"
_NUMBER = "number"
_NUMBER_OR_LENGTH = "number-or-length"
_INTEGER = "integer"
_TRACK = "track"
_OPAQUE = "opaque"

#: Curated property -> value category table. Anything outside this table and
#: without a vendor prefix is reported as ``unknown_property``.
_PROPERTIES: dict[str, str] = {
    # Box model and layout.
    "align-content": _OPAQUE,
    "align-items": _OPAQUE,
    "align-self": _OPAQUE,
    "aspect-ratio": _NUMBER,
    "block-size": _LENGTH_PERCENTAGE,
    "bottom": _LENGTH_PERCENTAGE,
    "box-sizing": _OPAQUE,
    "clear": _OPAQUE,
    "color-scheme": _OPAQUE,
    "container-name": _OPAQUE,
    "container-type": _OPAQUE,
    "content-visibility": _OPAQUE,
    "columns": _OPAQUE,
    "column-count": _INTEGER,
    "column-gap": _LENGTH_PERCENTAGE,
    "column-rule-color": _PAINT,
    "column-rule-style": _OPAQUE,
    "column-rule-width": _LENGTH,
    "column-span": _OPAQUE,
    "column-width": _LENGTH,
    "contain": _OPAQUE,
    "display": _OPAQUE,
    "flex": _OPAQUE,
    "flex-basis": _LENGTH_PERCENTAGE,
    "flex-direction": _OPAQUE,
    "flex-flow": _OPAQUE,
    "flex-grow": _NUMBER,
    "flex-shrink": _NUMBER,
    "flex-wrap": _OPAQUE,
    "float": _OPAQUE,
    "gap": _LENGTH_PERCENTAGE,
    "grid": _OPAQUE,
    "grid-area": _OPAQUE,
    "grid-auto-columns": _TRACK,
    "grid-auto-flow": _OPAQUE,
    "grid-auto-rows": _TRACK,
    "grid-column": _OPAQUE,
    "grid-column-end": _OPAQUE,
    "grid-column-start": _OPAQUE,
    "grid-row": _OPAQUE,
    "grid-row-end": _OPAQUE,
    "grid-row-start": _OPAQUE,
    "grid-template": _OPAQUE,
    "grid-template-areas": _OPAQUE,
    "grid-template-columns": _TRACK,
    "grid-template-rows": _TRACK,
    "height": _LENGTH_PERCENTAGE,
    "inline-size": _LENGTH_PERCENTAGE,
    "inset": _LENGTH_PERCENTAGE,
    "inset-block": _LENGTH_PERCENTAGE,
    "inset-block-end": _LENGTH_PERCENTAGE,
    "inset-block-start": _LENGTH_PERCENTAGE,
    "inset-inline": _LENGTH_PERCENTAGE,
    "inset-inline-end": _LENGTH_PERCENTAGE,
    "inset-inline-start": _LENGTH_PERCENTAGE,
    "justify-content": _OPAQUE,
    "justify-items": _OPAQUE,
    "justify-self": _OPAQUE,
    "left": _LENGTH_PERCENTAGE,
    "margin": _LENGTH_PERCENTAGE,
    "margin-block": _LENGTH_PERCENTAGE,
    "margin-block-end": _LENGTH_PERCENTAGE,
    "margin-block-start": _LENGTH_PERCENTAGE,
    "margin-bottom": _LENGTH_PERCENTAGE,
    "margin-inline": _LENGTH_PERCENTAGE,
    "margin-inline-end": _LENGTH_PERCENTAGE,
    "margin-inline-start": _LENGTH_PERCENTAGE,
    "margin-left": _LENGTH_PERCENTAGE,
    "margin-right": _LENGTH_PERCENTAGE,
    "margin-top": _LENGTH_PERCENTAGE,
    "max-height": _LENGTH_PERCENTAGE,
    "max-inline-size": _LENGTH_PERCENTAGE,
    "max-block-size": _LENGTH_PERCENTAGE,
    "max-width": _LENGTH_PERCENTAGE,
    "min-block-size": _LENGTH_PERCENTAGE,
    "min-height": _LENGTH_PERCENTAGE,
    "min-inline-size": _LENGTH_PERCENTAGE,
    "min-width": _LENGTH_PERCENTAGE,
    "object-fit": _OPAQUE,
    "object-position": _OPAQUE,
    "order": _INTEGER,
    "outline-offset": _LENGTH,
    "overflow": _OPAQUE,
    "overflow-wrap": _OPAQUE,
    "overflow-x": _OPAQUE,
    "overflow-y": _OPAQUE,
    "padding": _LENGTH_PERCENTAGE,
    "padding-block": _LENGTH_PERCENTAGE,
    "padding-block-end": _LENGTH_PERCENTAGE,
    "padding-block-start": _LENGTH_PERCENTAGE,
    "padding-bottom": _LENGTH_PERCENTAGE,
    "padding-inline": _LENGTH_PERCENTAGE,
    "padding-inline-end": _LENGTH_PERCENTAGE,
    "padding-inline-start": _LENGTH_PERCENTAGE,
    "padding-left": _LENGTH_PERCENTAGE,
    "padding-right": _LENGTH_PERCENTAGE,
    "padding-top": _LENGTH_PERCENTAGE,
    "place-content": _OPAQUE,
    "place-items": _OPAQUE,
    "place-self": _OPAQUE,
    "position": _OPAQUE,
    "resize": _OPAQUE,
    "right": _LENGTH_PERCENTAGE,
    "row-gap": _LENGTH_PERCENTAGE,
    "top": _LENGTH_PERCENTAGE,
    "visibility": _OPAQUE,
    "width": _LENGTH_PERCENTAGE,
    "z-index": _INTEGER,
    # Color, background, and borders.
    "accent-color": _PAINT,
    "background": _PAINT,
    "background-attachment": _OPAQUE,
    "background-blend-mode": _OPAQUE,
    "background-clip": _OPAQUE,
    "background-color": _PAINT,
    "background-image": _OPAQUE,
    "background-origin": _OPAQUE,
    "background-position": _OPAQUE,
    "background-repeat": _OPAQUE,
    "background-size": _OPAQUE,
    "border": _PAINT,
    "border-block": _PAINT,
    "border-block-color": _PAINT,
    "border-block-end": _PAINT,
    "border-block-start": _PAINT,
    "border-bottom": _PAINT,
    "border-bottom-color": _PAINT,
    "border-bottom-left-radius": _LENGTH_PERCENTAGE,
    "border-bottom-right-radius": _LENGTH_PERCENTAGE,
    "border-bottom-width": _LENGTH,
    "border-collapse": _OPAQUE,
    "border-color": _PAINT,
    "border-image": _OPAQUE,
    "border-inline": _PAINT,
    "border-inline-color": _PAINT,
    "border-inline-end": _PAINT,
    "border-inline-start": _PAINT,
    "border-left": _PAINT,
    "border-left-color": _PAINT,
    "border-left-width": _LENGTH,
    "border-radius": _LENGTH_PERCENTAGE,
    "border-right": _PAINT,
    "border-right-color": _PAINT,
    "border-right-width": _LENGTH,
    "border-spacing": _OPAQUE,
    "border-style": _OPAQUE,
    "border-top": _PAINT,
    "border-top-color": _PAINT,
    "border-top-left-radius": _LENGTH_PERCENTAGE,
    "border-top-right-radius": _LENGTH_PERCENTAGE,
    "border-top-width": _LENGTH,
    "border-width": _LENGTH,
    "box-shadow": _PAINT,
    "caret-color": _PAINT,
    "color": _COLOR,
    "column-rule": _PAINT,
    "fill": _PAINT,
    "flood-color": _PAINT,
    "lighting-color": _PAINT,
    "outline": _PAINT,
    "outline-color": _PAINT,
    "outline-style": _OPAQUE,
    "outline-width": _LENGTH,
    "stop-color": _PAINT,
    "stroke": _PAINT,
    "stroke-dasharray": _OPAQUE,
    "stroke-dashoffset": _OPAQUE,
    "stroke-linecap": _OPAQUE,
    "stroke-linejoin": _OPAQUE,
    "stroke-miterlimit": _OPAQUE,
    "stroke-opacity": _NUMBER,
    "stroke-width": _OPAQUE,
    "fill-opacity": _NUMBER,
    "fill-rule": _OPAQUE,
    "clip-rule": _OPAQUE,
    "color-interpolation": _OPAQUE,
    "dominant-baseline": _OPAQUE,
    "marker": _OPAQUE,
    "marker-end": _OPAQUE,
    "marker-mid": _OPAQUE,
    "marker-start": _OPAQUE,
    "paint-order": _OPAQUE,
    "shape-rendering": _OPAQUE,
    "text-anchor": _OPAQUE,
    "vector-effect": _OPAQUE,
    "text-decoration": _PAINT,
    "text-decoration-color": _PAINT,
    "text-shadow": _PAINT,
    # Typography.
    "direction": _OPAQUE,
    "font": _OPAQUE,
    "font-display": _OPAQUE,
    "font-family": _OPAQUE,
    "font-feature-settings": _OPAQUE,
    "font-size": _LENGTH_PERCENTAGE,
    "font-style": _OPAQUE,
    "font-variant": _OPAQUE,
    "font-weight": _INTEGER,
    "hyphens": _OPAQUE,
    "letter-spacing": _LENGTH,
    "line-height": _NUMBER_OR_LENGTH,
    "quotes": _OPAQUE,
    "tab-size": _NUMBER_OR_LENGTH,
    "text-align": _OPAQUE,
    "text-indent": _LENGTH_PERCENTAGE,
    "text-overflow": _OPAQUE,
    "text-transform": _OPAQUE,
    "vertical-align": _OPAQUE,
    "white-space": _OPAQUE,
    "word-break": _OPAQUE,
    "word-spacing": _LENGTH,
    "word-wrap": _OPAQUE,
    # Lists, tables, and media.
    "caption-side": _OPAQUE,
    "content": _OPAQUE,
    "counter-increment": _OPAQUE,
    "counter-reset": _OPAQUE,
    "empty-cells": _OPAQUE,
    "list-style": _OPAQUE,
    "list-style-image": _OPAQUE,
    "list-style-position": _OPAQUE,
    "list-style-type": _OPAQUE,
    "src": _OPAQUE,
    "table-layout": _OPAQUE,
    "unicode-range": _OPAQUE,
    # Effects, transitions, and animation.
    "animation": _OPAQUE,
    "animation-delay": _TIME,
    "animation-direction": _OPAQUE,
    "animation-duration": _TIME,
    "animation-fill-mode": _OPAQUE,
    "animation-iteration-count": _NUMBER,
    "animation-name": _OPAQUE,
    "animation-play-state": _OPAQUE,
    "animation-timing-function": _OPAQUE,
    "backdrop-filter": _OPAQUE,
    "backface-visibility": _OPAQUE,
    "clip-path": _OPAQUE,
    "filter": _OPAQUE,
    "isolation": _OPAQUE,
    "mix-blend-mode": _OPAQUE,
    "opacity": _NUMBER,
    "perspective": _LENGTH,
    "perspective-origin": _OPAQUE,
    "rotate": _ANGLE,
    "transform": _OPAQUE,
    "transform-origin": _OPAQUE,
    "transform-style": _OPAQUE,
    "transition": _OPAQUE,
    "transition-delay": _TIME,
    "transition-duration": _TIME,
    "transition-property": _OPAQUE,
    "transition-timing-function": _OPAQUE,
    "animation-timeline": _OPAQUE,
    "anchor-name": _OPAQUE,
    "field-sizing": _OPAQUE,
    "interpolate-size": _OPAQUE,
    "interactivity": _OPAQUE,
    "mask": _OPAQUE,
    "mask-clip": _OPAQUE,
    "mask-composite": _OPAQUE,
    "mask-image": _OPAQUE,
    "mask-mode": _OPAQUE,
    "mask-origin": _OPAQUE,
    "mask-position": _OPAQUE,
    "mask-repeat": _OPAQUE,
    "mask-size": _OPAQUE,
    "mask-type": _OPAQUE,
    "offset-anchor": _OPAQUE,
    "offset-distance": _LENGTH_PERCENTAGE,
    "offset-path": _OPAQUE,
    "offset-rotate": _OPAQUE,
    "position-anchor": _OPAQUE,
    "position-area": _OPAQUE,
    "position-try": _OPAQUE,
    "position-visibility": _OPAQUE,
    "reading-flow": _OPAQUE,
    "reading-order": _OPAQUE,
    "scroll-timeline": _OPAQUE,
    "scroll-timeline-name": _OPAQUE,
    "text-box": _OPAQUE,
    "text-box-edge": _OPAQUE,
    "text-box-trim": _OPAQUE,
    "text-decoration-skip-ink": _OPAQUE,
    "text-decoration-thickness": _LENGTH_PERCENTAGE,
    "text-emphasis": _OPAQUE,
    "text-emphasis-color": _PAINT,
    "text-emphasis-position": _OPAQUE,
    "text-emphasis-style": _OPAQUE,
    "text-underline-offset": _LENGTH_PERCENTAGE,
    "text-underline-position": _OPAQUE,
    "view-timeline": _OPAQUE,
    "view-timeline-axis": _OPAQUE,
    "view-timeline-name": _OPAQUE,
    "view-transition-class": _OPAQUE,
    "view-transition-name": _OPAQUE,
    # Interaction and scrolling.
    "appearance": _OPAQUE,
    "cursor": _OPAQUE,
    "overscroll-behavior": _OPAQUE,
    "pointer-events": _OPAQUE,
    "scroll-behavior": _OPAQUE,
    "scroll-margin": _LENGTH_PERCENTAGE,
    "scroll-margin-bottom": _LENGTH_PERCENTAGE,
    "scroll-margin-left": _LENGTH_PERCENTAGE,
    "scroll-margin-right": _LENGTH_PERCENTAGE,
    "scroll-margin-top": _LENGTH_PERCENTAGE,
    "scroll-padding": _LENGTH_PERCENTAGE,
    "scroll-padding-bottom": _LENGTH_PERCENTAGE,
    "scroll-padding-left": _LENGTH_PERCENTAGE,
    "scroll-padding-right": _LENGTH_PERCENTAGE,
    "scroll-padding-top": _LENGTH_PERCENTAGE,
    "scroll-snap-align": _OPAQUE,
    "scroll-snap-type": _OPAQUE,
    "scrollbar-color": _PAINT,
    "scrollbar-width": _OPAQUE,
    "font-synthesis": _OPAQUE,
    "print-color-adjust": _OPAQUE,
    "text-size-adjust": _OPAQUE,
    "text-wrap": _OPAQUE,
    "touch-action": _OPAQUE,
    "user-select": _OPAQUE,
    "will-change": _OPAQUE,
}

#: CSS-wide keywords accepted for every property.
_GLOBAL_KEYWORDS = frozenset(
    {"inherit", "initial", "unset", "revert", "revert-layer"}
)

#: Functions whose arguments are never analyzed (unresolvable at parse time).
_OPAQUE_FUNCTIONS_RE = re.compile(
    r"\b(?:var|env|calc|clamp|min|max|attr|counter|counters|url)\s*\(",
    re.IGNORECASE,
)

_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_ANY_HASH_RE = re.compile(r"#[0-9A-Za-z_-]+")
_COMPONENT_RE = re.compile(r"(?<![\w#.-])(-?[A-Za-z_][\w-]*)\s*(\()?")
_NUMBER_WITH_UNIT_RE = re.compile(
    r"(?<![\w.#-])([+-]?(?:\d+(?:\.\d+)?|\.\d+))([A-Za-z%]+)?"
)
_COLOR_FUNCTION_RE = re.compile(
    r"(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color|color-mix|"
    r"light-dark|device-cmyk|gray)\s*\(",
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

#: CSS named colors (CSS Color Module Level 4) plus CSS-wide color keywords.
_NAMED_COLORS = frozenset(
    """
    aliceblue antiquewhite aqua aquamarine azure beige bisque black
    blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse
    chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan
    darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta
    darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
    darkslateblue darkslategray darkslategrey darkturquoise darkviolet
    deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite
    forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green
    greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender
    lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
    lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon
    lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue
    lightyellow lime limegreen linen magenta maroon mediumaquamarine
    mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue
    mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
    mistyrose moccasin navajowhite navy oldlace olive olivedrab orange
    orangered orchid palegoldenrod palegreen paleturquoise palevioletred
    papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red
    rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell
    sienna silver skyblue slateblue slategray slategrey snow springgreen
    steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke
    yellow yellowgreen
    """.split()
)

#: Non-color keywords accepted where a color may appear.
_PAINT_KEYWORDS = frozenset(
    {
        "auto",
        "border-box",
        "bottom",
        "center",
        "clone",
        "contain",
        "content-box",
        "cover",
        "currentcolor",
        "dashed",
        "dotted",
        "double",
        "fixed",
        "from-image",
        "groove",
        "hidden",
        "inset",
        "left",
        "line-through",
        "local",
        "medium",
        "no-repeat",
        "none",
        "outset",
        "overline",
        "padding-box",
        "repeat",
        "repeat-x",
        "repeat-y",
        "ridge",
        "right",
        "round",
        "scroll",
        "slice",
        "solid",
        "space",
        "text",
        "thick",
        "thin",
        "top",
        "transparent",
        "underline",
        "wavy",
    }
) | frozenset(
    {
        "canvas",
        "canvastext",
        "linktext",
        "visitedtext",
        "activetext",
        "buttonface",
        "buttontext",
        "field",
        "fieldtext",
        "highlight",
        "highlighttext",
        "selecteditem",
        "selecteditemtext",
        "mark",
        "marktext",
        "graytext",
        "accentcolor",
        "accentcolortext",
        "currentColor",
    }
)

_LENGTH_UNITS = frozenset(
    {
        "px",
        "em",
        "rem",
        "ex",
        "ch",
        "cap",
        "ic",
        "lh",
        "rlh",
        "vw",
        "vh",
        "vmin",
        "vmax",
        "dvw",
        "dvh",
        "dvmin",
        "dvmax",
        "svw",
        "svh",
        "lvw",
        "lvh",
        "cm",
        "mm",
        "q",
        "in",
        "pt",
        "pc",
    }
)
_TIME_UNITS = frozenset({"s", "ms"})
_ANGLE_UNITS = frozenset({"deg", "grad", "rad", "turn"})
_TRACK_UNITS = frozenset({"fr"})

#: Category -> units allowed on a non-zero number of that category.
_UNIT_RULES: dict[str, frozenset[str]] = {
    _LENGTH: _LENGTH_UNITS,
    _LENGTH_PERCENTAGE: _LENGTH_UNITS | {"%"},
    _TIME: _TIME_UNITS,
    _ANGLE: _ANGLE_UNITS,
    _TRACK: _LENGTH_UNITS | {"%"} | _TRACK_UNITS,
    _NUMBER: frozenset({"%"}),
    _NUMBER_OR_LENGTH: _LENGTH_UNITS | {"%"},
    _INTEGER: frozenset(),
}

#: Categories whose numeric values may omit the unit (zero always may).
_UNITLESS_CATEGORIES = frozenset({_NUMBER, _NUMBER_OR_LENGTH, _INTEGER})



class CssValidator:
    """Perform structural checks on a CSS stylesheet."""

    language = "css"
    coverage = COVERAGE

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
                },
                "coverage": dict(COVERAGE),
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

    raw_segment = original[block.segment_start:end]
    raw_value = raw_segment[leading + colon + 1 :]
    issues.extend(
        _check_declaration_value(
            property_name,
            raw_value,
            context,
            line,
            column,
        )
    )


def _check_declaration_value(
    property_name: str,
    raw_value: str,
    context: ValidationContext,
    line: int,
    column: int,
) -> list[LanguageIssue]:
    """Validate ``property_name`` and its value against the curated table."""
    lowered = property_name.lower()
    if lowered.startswith("--"):
        # Custom properties accept arbitrary tokens by design.
        return []

    category = _PROPERTIES.get(lowered)
    if category is None:
        if lowered.startswith("-"):
            # Vendor-prefixed properties are outside the specification table.
            return []
        return [
            _issue(
                "low",
                f"Unknown CSS property '{property_name}'.",
                "unknown_property",
                context,
                line,
                column,
            )
        ]

    value = _clean_value(raw_value)
    if not value or _is_opaque_value(value):
        return []

    issues: list[LanguageIssue] = []
    if category in {_COLOR, _PAINT}:
        issues.extend(_check_value_colors(value, category, context, line, column))
    unit_rule = _UNIT_RULES.get(category)
    if unit_rule is not None:
        issues.extend(
            _check_value_units(
                value,
                category,
                unit_rule,
                context,
                line,
                column,
            )
        )
    return issues


def _clean_value(raw_value: str) -> str:
    """Return the declaration value without comments and ``!important``."""
    value = _COMMENT_RE.sub(" ", raw_value)
    value = _IMPORTANT_RE.sub(" ", value)
    return value.strip()


def _is_opaque_value(value: str) -> bool:
    """Return ``True`` when the value cannot be analyzed deterministically."""
    if value.lower() in _GLOBAL_KEYWORDS:
        return True
    return _OPAQUE_FUNCTIONS_RE.search(value) is not None


def _paren_depths(value: str) -> list[int]:
    """Return the parenthesis depth at each character position of ``value``."""
    depths = [0] * (len(value) + 1)
    depth = 0
    for index, char in enumerate(value):
        depths[index] = depth
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
    depths[len(value)] = depth
    return depths


def _check_value_colors(
    value: str,
    category: str,
    context: ValidationContext,
    line: int,
    column: int,
) -> list[LanguageIssue]:
    issues: list[LanguageIssue] = []
    for match in _ANY_HASH_RE.finditer(value):
        if _HEX_COLOR_RE.fullmatch(match.group(0)) is not None:
            continue
        issues.append(
            _issue(
                "medium",
                f"'{match.group(0)}' is not a valid hexadecimal color.",
                "invalid_value",
                context,
                line,
                column,
            )
        )

    if category == _COLOR:
        if _is_single_color(value):
            return issues
        if issues:
            # A malformed hex color was already reported; do not duplicate it.
            return issues
        return [
            _issue(
                "medium",
                f"'{value.strip()}' is not a valid color.",
                "invalid_value",
                context,
                line,
                column,
            )
        ]

    depths = _paren_depths(value)
    for match in _COMPONENT_RE.finditer(value):
        if depths[match.start()] != 0:
            continue
        if match.group(2) is not None:
            # A function such as ``linear-gradient(...)``; arguments are opaque.
            continue
        word = match.group(1)
        lowered = word.lower()
        if lowered in _NAMED_COLORS or lowered in _PAINT_KEYWORDS:
            continue
        if lowered in _GLOBAL_KEYWORDS:
            continue
        issues.append(
            _issue(
                "medium",
                f"'{word}' is not a valid color or keyword for '{category}' values.",
                "invalid_value",
                context,
                line,
                column,
            )
        )
    return issues


def _is_single_color(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if (
        _HEX_COLOR_RE.fullmatch(stripped) is not None
        or _COLOR_FUNCTION_RE.match(stripped) is not None
    ):
        return True
    lowered = stripped.lower()
    if lowered in _GLOBAL_KEYWORDS:
        return True
    return lowered in _NAMED_COLORS or lowered in _PAINT_KEYWORDS


def _check_value_units(
    value: str,
    category: str,
    allowed_units: frozenset[str],
    context: ValidationContext,
    line: int,
    column: int,
) -> list[LanguageIssue]:
    issues: list[LanguageIssue] = []
    depths = _paren_depths(value)
    for match in _NUMBER_WITH_UNIT_RE.finditer(value):
        if depths[match.start()] != 0:
            # Numbers inside functions (calc, gradients, shapes) are opaque.
            continue
        number = match.group(1)
        unit = (match.group(2) or "").lower()
        if unit == "":
            try:
                is_zero = float(number) == 0
            except ValueError:
                continue
            if is_zero or category in _UNITLESS_CATEGORIES:
                continue
            issues.append(
                _issue(
                    "medium",
                    f"Value '{number}' for a '{category}' property is missing a unit.",
                    "invalid_unit",
                    context,
                    line,
                    column,
                )
            )
            continue
        if unit in allowed_units:
            continue
        issues.append(
            _issue(
                "medium",
                f"Unit '{unit}' is not valid for a '{category}' property.",
                "invalid_unit",
                context,
                line,
                column,
            )
        )
    return issues


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
