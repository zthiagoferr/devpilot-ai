"""Deterministic language detection based on path and source markers.

Detection never asks an LLM. A manual request always wins, an unambiguous
extension is trusted (with a few guards for ambiguous Protheus/C header
extensions), and content markers are only used as a fallback.
"""

from __future__ import annotations

import json
import re

from app.languages.base import (
    AUTO_CONFIDENCE_THRESHOLD,
    SUPPORTED_LANGUAGES,
    Detection,
    UnsupportedLanguageError,
)
from app.languages.spec import SPECS

#: Extension (lowercase, with the dot) -> language, derived from :data:`SPECS`.
LANGUAGE_EXTENSIONS: dict[str, str] = {
    extension: spec.id
    for spec in SPECS.values()
    for extension in spec.extensions
}

#: Baseline confidence assigned to each extension, derived from :data:`SPECS`.
#: ``.prg`` and ``.ch`` are shared by other ecosystems and are therefore less
#: conclusive.
EXTENSION_CONFIDENCE: dict[str, float] = {
    extension: spec.confidence_by_extension[extension]
    for spec in SPECS.values()
    for extension in spec.extensions
}

_AUTO_REQUEST_VALUES = frozenset({"auto", ""})

_JS_EXTENSIONS = frozenset({".js", ".mjs", ".cjs"})

_JSON_JS_MARKER = re.compile(
    r"\b(?:function|const|let|var|class|import|export|document|console|"
    r"debugger|eval)\b|=>|//|/\*",
    re.IGNORECASE,
)

_C_LIKE_SIGNALS = (
    (re.compile(r"#\s*include\s*<", re.IGNORECASE), 0.30),
    (re.compile(r"\btypedef\b", re.IGNORECASE), 0.20),
    (re.compile(r"\bstruct\s+[A-Za-z_]\w*\s*\{", re.IGNORECASE), 0.20),
    (re.compile(r'extern\s+"c"', re.IGNORECASE), 0.20),
    (re.compile(r"^[ \t]*#\s*ifndef\b", re.IGNORECASE | re.MULTILINE), 0.10),
    (re.compile(r"^[ \t]*#\s*pragma\b", re.IGNORECASE | re.MULTILINE), 0.10),
    (re.compile(r"\b(?:printf|malloc|sizeof)\s*\(", re.IGNORECASE), 0.10),
    (re.compile(r"\bint\s+main\s*\(", re.IGNORECASE), 0.20),
)


def language_for_extension(path: str | None) -> str | None:
    """Return the language suggested by ``path``, or ``None``.

    The lookup is case-insensitive, accepts Windows separators, and ignores a
    query string or fragment appended to the file name.
    """
    extension = _extension_of(path)
    if extension is None:
        return None
    return LANGUAGE_EXTENSIONS.get(extension)


def supported_extensions() -> frozenset[str]:
    """Return every extension understood by the detector."""
    return frozenset(LANGUAGE_EXTENSIONS)


def detect_language(
    source: str,
    *,
    path: str | None = None,
    requested: str | None = None,
) -> Detection:
    """Detect the language of ``source``.

    ``requested`` accepts one of :data:`SUPPORTED_LANGUAGES`, ``"auto"``, or
    ``None``. Any other non-empty value raises
    :class:`~app.languages.base.UnsupportedLanguageError`; this keeps a typo in
    an API payload from silently selecting a different language.
    """
    manual = _normalize_requested(requested)
    if manual is not None:
        return Detection(
            language=manual,
            source="manual",
            confidence=1.0,
            reason="manual_request",
            candidates=((manual, 1.0),),
        )

    text = _strip_bom(source or "")
    extension = _extension_of(path)

    if extension is not None and extension in LANGUAGE_EXTENSIONS:
        return _detect_from_extension(
            text,
            extension=extension,
            language=LANGUAGE_EXTENSIONS[extension],
        )

    return _detect_from_content(text)


def _normalize_requested(requested: str | None) -> str | None:
    if requested is None:
        return None
    if not isinstance(requested, str):
        raise UnsupportedLanguageError(str(requested))
    normalized = requested.strip().lower()
    if normalized in _AUTO_REQUEST_VALUES:
        return None
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    raise UnsupportedLanguageError(requested)


def _extension_of(path: str | None) -> str | None:
    if path is None:
        return None
    if not isinstance(path, str):
        try:
            path = str(path)
        except Exception:
            return None
    if not path.strip():
        return None
    candidate = path.replace("\\", "/").split("#", 1)[0].split("?", 1)[0]
    name = candidate.rsplit("/", 1)[-1]
    if "." not in name:
        return None
    extension = "." + name.rsplit(".", 1)[-1].lower()
    if extension == ".":
        return None
    return extension


def _strip_bom(source: str) -> str:
    return source[1:] if source.startswith("\ufeff") else source


def _strip_preprocessor_lines(text: str) -> str:
    """Remove preprocessor directives before scoring plain ADVPL markers."""
    return re.sub(r"^[ \t]*#[^\n]*", "", text, flags=re.MULTILINE)


def _advpl_score(text: str) -> float:
    score = 0.0
    if re.search(r"^[ \t]*#\s*include\b", text, re.IGNORECASE | re.MULTILINE):
        score += 0.30

    body = _strip_preprocessor_lines(text)
    if re.search(
        r"^[ \t]*(?:user\s+function|static\s+function|main\s+function)\b",
        body,
        re.IGNORECASE | re.MULTILINE,
    ):
        score += 0.30
    # A bare ``function`` header is too weak to be an ADVPL signal on its own:
    # ``function name(...)`` is idiomatic JavaScript and would otherwise
    # outrank the JavaScript markers and send the source to the ADVPL
    # validator (false ``unclosed_block``). The ADVPL-specific prefixes above
    # keep their own weight and never match here, so there is no double count.
    if re.search(
        r"^[ \t]*function\b",
        body,
        re.IGNORECASE | re.MULTILINE,
    ):
        score += 0.10
    if re.search(
        r"^[ \t]*(?:local|private|public)\b",
        body,
        re.IGNORECASE | re.MULTILINE,
    ):
        score += 0.20
    if re.search(r"\bbegin\s+sequence\b", body, re.IGNORECASE):
        score += 0.20
    if ":=" in body:
        score += 0.15
    if re.search(r"\b(?:endif|enddo|endcase)\b", body, re.IGNORECASE):
        score += 0.15
    if re.search(r"\b(?:msginfo|reclock)\b|\bfw[a-z]\w*", body, re.IGNORECASE):
        score += 0.10
    # Short ADVPL snippets often omit ``Local``/function declarations. A plain
    # ``If`` alone is too weak (it also occurs in C-like code), so the bonus is
    # conditional on a real ADVPL signal: a matching ``EndIf``, ``MsgInfo``, or
    # ``Return Nil``.
    has_if = bool(
        re.search(
            r"^[ \t]*if\b",
            body,
            re.IGNORECASE | re.MULTILINE,
        )
    )
    if has_if and re.search(r"\bendif\b", body, re.IGNORECASE):
        score += 0.20
    if has_if and re.search(r"\bmsginfo\b", body, re.IGNORECASE):
        score += 0.15
    if re.search(r"\breturn[ \t]+nil\b", body, re.IGNORECASE):
        score += 0.15
    return min(1.0, score)


def _c_like_score(text: str) -> float:
    score = sum(
        weight for pattern, weight in _C_LIKE_SIGNALS if pattern.search(text)
    )
    return min(1.0, score)


def _go_like_score(text: str) -> float:
    score = 0.0
    if re.search(r"^[ \t]*package[ \t]+[A-Za-z_]\w*", text, re.MULTILINE):
        score += 0.40
    if re.search(r"^[ \t]*func[ \t]+[A-Za-z_]\w*", text, re.MULTILINE):
        score += 0.30
    if re.search(r"\bfmt\.", text):
        score += 0.20
    return min(1.0, score)


def _has_advpl_specific_markers(text: str) -> bool:
    return bool(
        re.search(
            r"^[ \t]*(?:user[ \t]+function|static[ \t]+function|"
            r"main[ \t]+function|local|private|public)\b",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        or re.search(r"\bbegin[ \t]+sequence\b", text, re.IGNORECASE)
        or ":=" in text
        or re.search(r"\b(?:endif|enddo|endcase)\b", text, re.IGNORECASE)
        or re.search(r"\b(?:msginfo|reclock)\b|\bfw[a-z]\w*", text, re.IGNORECASE)
        or re.search(r"\breturn[ \t]+nil\b", text, re.IGNORECASE)
        or (
            re.search(
                r"^[ \t]*if\b",
                text,
                re.IGNORECASE | re.MULTILINE,
            )
            and re.search(r"\bendif\b", text, re.IGNORECASE)
        )
    )


def _python_score(text: str) -> float:
    score = 0.0
    if re.search(
        r"^[ \t]*(?:async[ \t]+def|def|class|import|from)\b",
        text,
        re.MULTILINE,
    ):
        score += 0.40
    if re.search(r"\bprint\s*\(", text):
        score += 0.20
    if re.search(r"^[ \t]*if[ \t]+__name__[ \t]*==", text, re.MULTILINE):
        score += 0.30
    return min(1.0, score)


def _html_score(text: str) -> float:
    score = 0.0
    if re.search(r"<!doctype\s+html\b", text, re.IGNORECASE):
        score += 0.40
    if re.search(r"<html\b", text, re.IGNORECASE):
        score += 0.30
    if re.search(r"<head\b", text, re.IGNORECASE):
        score += 0.15
    if re.search(r"<body\b", text, re.IGNORECASE):
        score += 0.15
    return min(1.0, score)


def _css_score(text: str) -> float:
    score = 0.0
    if re.search(r"@media\b", text, re.IGNORECASE):
        score += 0.20
    if re.search(r"@import\b", text, re.IGNORECASE):
        score += 0.20
    if re.search(r":root\b", text):
        score += 0.10
    # A brace containing at least one ``property: value;`` declaration.
    blocks = re.findall(r"\{[^{}]*?[A-Za-z-]+\s*:\s*[^{};]+;", text)
    score += min(0.60, 0.20 * len(blocks))
    return min(1.0, score)


def _javascript_score(text: str) -> float:
    score = 0.0
    checks = (
        (r"\bfunction\b", 0.20),
        (r"\bconst\b", 0.25),
        (r"\blet\b", 0.20),
        (r"=>", 0.20),
        (r"^[ \t]*import\b", 0.20),
        (r"\bdocument\.", 0.20),
        (r"\bconsole\.", 0.20),
        (r"^[ \t]*export\b", 0.10),
    )
    for pattern, weight in checks:
        flags = re.IGNORECASE | (re.MULTILINE if pattern.startswith("^") else 0)
        if re.search(pattern, text, flags):
            score += weight
    return min(1.0, score)


def _content_scores(text: str) -> dict[str, float]:
    return {
        "python": _python_score(text),
        "advpl": _advpl_score(text),
        "html": _html_score(text),
        "css": _css_score(text),
        "javascript": _javascript_score(text),
    }


def _is_json_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
    except (ValueError, TypeError):
        return False
    return _JSON_JS_MARKER.search(stripped) is None


def _detect_from_extension(
    text: str,
    *,
    extension: str,
    language: str,
) -> Detection:
    base_confidence = EXTENSION_CONFIDENCE[extension]
    scores = _content_scores(text)
    advpl_score = scores["advpl"]

    if extension in _JS_EXTENSIONS and _is_json_only(text):
        return Detection(
            language="javascript",
            source="extension",
            confidence=0.70,
            reason="json_only",
            candidates=(("javascript", 0.70),),
        )

    if extension == ".ch":
        c_score = _c_like_score(text)
        has_angle_include = bool(
            re.search(r"#[ \t]*include[ \t]*<", text, re.IGNORECASE)
        )
        body = _strip_preprocessor_lines(text)
        has_include_guard = bool(
            re.search(
                r"^[ \t]*#[ \t]*ifndef\b", text, re.IGNORECASE | re.MULTILINE
            )
        ) and bool(
            re.search(
                r"^[ \t]*#[ \t]*define\b", text, re.IGNORECASE | re.MULTILINE
            )
        )
        c_like_header = (
            (c_score >= 0.40 and c_score > advpl_score)
            or (
                has_angle_include
                and c_score >= 0.30
                and not _has_advpl_specific_markers(body)
            )
            or (c_score >= 0.20 and advpl_score == 0.0)
            or (has_include_guard and advpl_score == 0.0)
        )
        if c_like_header:
            return _unknown("c_like_header")
        confidence = base_confidence
        if advpl_score >= 0.50:
            confidence = 0.95
        elif advpl_score >= 0.30:
            confidence = 0.85
        return _with_candidates("advpl", "extension", confidence, "advpl_header")

    if extension == ".prg":
        c_score = _c_like_score(text)
        python_score = scores["python"]
        go_score = _go_like_score(text)
        dominant_c = c_score >= 0.40 and c_score > advpl_score
        dominant_python = python_score >= 0.40 and python_score > advpl_score
        dominant_go = go_score >= 0.30 and go_score > advpl_score
        if dominant_c or dominant_python or dominant_go:
            if dominant_go:
                reason = "go_like_content"
            elif dominant_c:
                reason = "c_like_content"
            else:
                reason = "python_like_content"
            return _unknown(reason)
        confidence = 0.90 if advpl_score >= 0.30 else base_confidence
        return _with_candidates("advpl", "extension", confidence, "advpl_source")

    return _with_candidates(language, "extension", base_confidence, "known_extension")


def _detect_from_content(text: str) -> Detection:
    scores = _content_scores(text)

    if _is_json_only(text):
        return Detection(
            language="javascript",
            source="content",
            confidence=0.70,
            reason="json_only",
            candidates=(("javascript", 0.70),),
        )

    ranked = sorted(
        (
            (language, score)
            for language, score in scores.items()
            if score > 0.0
        ),
        key=lambda item: (-item[1], SUPPORTED_LANGUAGES.index(item[0])),
    )
    if not ranked or ranked[0][1] < 0.20:
        return _unknown("no_language_markers")

    best_language, best_score = ranked[0]
    confidence = min(0.90, AUTO_CONFIDENCE_THRESHOLD + (best_score * 0.40))
    candidates = ((best_language, round(confidence, 2)),) + tuple(
        (language, round(min(0.55, score), 2))
        for language, score in ranked[1:3]
    )
    return Detection(
        language=best_language,  # type: ignore[arg-type]
        source="content",
        confidence=round(confidence, 2),
        reason=f"{best_language}_markers",
        candidates=candidates,
    )


def _with_candidates(
    language: str,
    source: str,
    confidence: float,
    reason: str,
) -> Detection:
    return Detection(
        language=language,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        confidence=confidence,
        reason=reason,
        candidates=((language, confidence),),
    )


def _unknown(reason: str) -> Detection:
    return Detection(
        language="unknown",
        source="fallback" if reason == "no_language_markers" else "content",
        confidence=0.0,
        reason=reason,
        candidates=(),
    )
