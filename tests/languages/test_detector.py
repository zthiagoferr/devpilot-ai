"""Tests for language detection."""

from __future__ import annotations

import pytest

from app.languages.base import UnsupportedLanguageError
from app.languages.detector import (
    detect_language,
    language_for_extension,
    supported_extensions,
)

ADVPL_SOURCE = (
    "User Function Foo()\n"
    "Local nValue := 1\n"
    "If nValue > 0\n"
    "  MsgInfo('ok')\n"
    "EndIf\n"
    "Return Nil\n"
)

PYTHON_SOURCE = "import os\n\ndef run():\n    return os.name\n"
HTML_SOURCE = "<!DOCTYPE html><html><head></head><body>x</body></html>"
CSS_SOURCE = "body { color: red; }\n"
JAVASCRIPT_SOURCE = "const value = 1;\nconsole.log(value);\n"


def test_manual_request_wins_over_extension() -> None:
    detection = detect_language(
        "const value = 1;",
        path="example.py",
        requested="javascript",
    )

    assert detection.language == "javascript"
    assert detection.source == "manual"
    assert detection.confidence == 1.0
    assert detection.reason == "manual_request"
    assert detection.candidates == (("javascript", 1.0),)


@pytest.mark.parametrize("requested", [None, "auto", "AUTO"])
def test_auto_request_is_not_manual(requested: str | None) -> None:
    detection = detect_language(PYTHON_SOURCE, path="example.py", requested=requested)
    assert detection.source != "manual"
    assert detection.language == "python"


def test_invalid_requested_language_raises() -> None:
    with pytest.raises(UnsupportedLanguageError):
        detect_language(PYTHON_SOURCE, path="example.py", requested="ruby")


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("app/main.py", "python"),
        ("app/types.pyi", "python"),
        ("app/foo.prw", "advpl"),
        ("app/foo.prg", "advpl"),
        ("app/foo.ch", "advpl"),
        ("app/index.html", "html"),
        ("app/index.htm", "html"),
        ("app/styles.css", "css"),
        ("app/main.js", "javascript"),
        ("app/module.mjs", "javascript"),
        ("app/legacy.cjs", "javascript"),
    ],
)
def test_extension_detection(path: str, language: str) -> None:
    detection = detect_language("", path=path)
    assert detection.language == language
    assert detection.source == "extension"
    assert detection.confidence >= 0.4


def test_extension_lookup_is_case_insensitive_and_ignores_query() -> None:
    assert language_for_extension("APP/MAIN.PY") == "python"
    assert language_for_extension("app/main.js?v=1") == "javascript"
    assert language_for_extension("app/main.css#fragment") == "css"
    assert language_for_extension("Makefile") is None
    assert language_for_extension(None) is None


def test_supported_extensions() -> None:
    extensions = supported_extensions()
    assert ".py" in extensions
    assert ".prw" in extensions
    assert ".html" in extensions
    assert ".css" in extensions
    assert ".js" in extensions


def test_c_like_ch_is_unknown() -> None:
    source = (
        "#ifndef FOO_H\n"
        "#define FOO_H\n"
        "typedef struct Foo { int value; } Foo;\n"
        "#endif\n"
    )
    detection = detect_language(source, path="include/foo.ch")

    assert detection.language == "unknown"
    assert detection.confidence == 0.0
    assert detection.reason == "c_like_header"


def test_c_include_guard_ch_is_unknown() -> None:
    source = (
        "#ifndef FOO_H\n"
        "#define FOO_H\n"
        "int foo(void);\n"
        "#endif\n"
    )
    detection = detect_language(source, path="include/foo.ch")

    assert detection.language == "unknown"
    assert detection.reason == "c_like_header"


def test_c_include_only_ch_is_unknown() -> None:
    detection = detect_language('#include <stdint.h>\n', path="include/types.ch")
    assert detection.language == "unknown"
    assert detection.reason == "c_like_header"


def test_advpl_ch_with_angle_include_and_advpl_markers_stays_advpl() -> None:
    detection = detect_language(
        '#include <custom.ch>\nUser Function Foo()\nReturn Nil\n',
        path="include/custom.ch",
    )
    assert detection.language == "advpl"


def test_advpl_ch_stays_advpl() -> None:
    detection = detect_language(
        '#Include "protheus.ch"\n#Ifdef __X__\n#Endif\n',
        path="include/custom.ch",
    )

    assert detection.language == "advpl"
    assert detection.confidence >= 0.7


def test_advpl_prg_stays_advpl() -> None:
    detection = detect_language(ADVPL_SOURCE, path="sources/foo.prg")
    assert detection.language == "advpl"
    assert detection.confidence >= 0.6


def test_go_like_prg_is_unknown() -> None:
    source = (
        'package main\n\nimport "fmt"\n\n'
        'func main() { fmt.Println("hello") }\n'
    )
    detection = detect_language(source, path="tools/foo.prg")

    assert detection.language == "unknown"
    assert detection.reason in {"python_like_content", "c_like_content", "go_like_content"}


def test_go_prg_without_python_import_is_unknown() -> None:
    detection = detect_language(
        "package main\n\nfunc main() {}\n",
        path="tools/foo.prg",
    )
    assert detection.language == "unknown"
    assert detection.reason == "go_like_content"


def test_go_prg_with_only_a_function_is_unknown() -> None:
    detection = detect_language("func main() {}\n", path="tools/foo.prg")
    assert detection.language == "unknown"
    assert detection.reason == "go_like_content"


def test_c_like_prg_is_unknown() -> None:
    source = "#include <stdio.h>\nint main() { printf(\"x\"); return 0; }\n"
    detection = detect_language(source, path="tools/foo.prg")

    assert detection.language == "unknown"
    assert detection.reason == "c_like_content"


def test_prw_advpl_detection() -> None:
    detection = detect_language(ADVPL_SOURCE, path="sources/foo.prw")
    assert detection.language == "advpl"
    assert detection.source == "extension"
    assert detection.confidence >= 0.9


def test_json_only_javascript() -> None:
    detection = detect_language('{"name": "value", "items": [1, 2]}', path="data.js")

    assert detection.language == "javascript"
    assert detection.confidence == 0.7
    assert detection.reason == "json_only"


def test_bom_and_crlf_are_tolerated() -> None:
    detection = detect_language(
        "\ufeffdef run():\r\n    return 1\r\n",
        path="app/main.py",
    )
    assert detection.language == "python"


@pytest.mark.parametrize(
    ("source", "language"),
    [
        (PYTHON_SOURCE, "python"),
        (ADVPL_SOURCE, "advpl"),
        (HTML_SOURCE, "html"),
        (CSS_SOURCE, "css"),
        (JAVASCRIPT_SOURCE, "javascript"),
    ],
)
def test_content_detection_without_extension(source: str, language: str) -> None:
    detection = detect_language(source)

    assert detection.language == language
    assert detection.source == "content"
    assert detection.confidence >= 0.6
    assert detection.candidates


def test_fallback_unknown() -> None:
    detection = detect_language("hello, this is just prose.\n")

    assert detection.language == "unknown"
    assert detection.source == "fallback"
    assert detection.confidence == 0.0
    assert detection.candidates == ()


def test_unknown_extension_can_use_content_markers() -> None:
    detection = detect_language(PYTHON_SOURCE, path="scripts/tool.txt")
    assert detection.language == "python"
    assert detection.source == "content"
